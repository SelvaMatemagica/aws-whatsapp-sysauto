from datetime import datetime, timezone

from app.automations.engine.context import ActionContext
from app.automations.engine.registry import ACTION_REGISTRY
from app.automations.services import runs_service


async def execute_run(run_id: str, event: dict) -> None:
    run = await runs_service.load_run(run_id)
    if not run:
        return

    automation = run.get("automation") or {}
    actions = automation.get("actions") or []
    step_index = int(run.get("current_step_index") or 0)

    ctx = ActionContext(
        run_id=run_id,
        account_id=run["account_id"],
        contact_id=run["contact_id"],
        conversation_id=run["conversation_id"],
        event=event,
        variables=run.get("variables") or {},
        automation=automation,
        current_step_index=step_index,
    )

    while step_index < len(actions):
        action = actions[step_index]
        action_type = action.get("type")
        config = action.get("config") or {}

        handler = ACTION_REGISTRY.get(action_type)
        if not handler:
            await runs_service.log_step(
                run_id,
                step_index,
                "step_failed",
                input_data=action,
                error=f"Acción no soportada: {action_type}",
            )
            await runs_service.mark_run_failed(run_id, f"Acción no soportada: {action_type}")
            return

        await runs_service.log_step(run_id, step_index, "step_started", input_data=action)

        try:
            result = await handler.execute(ctx, config)
        except Exception as exc:
            await runs_service.log_step(
                run_id,
                step_index,
                "step_failed",
                input_data=action,
                error=str(exc),
            )
            await runs_service.mark_run_failed(run_id, str(exc))
            return

        if result.status == "waiting":
            await runs_service.log_step(
                run_id,
                step_index,
                "step_waiting",
                input_data=action,
                output_data=result.output,
            )
            step_index += 1
            await runs_service.update_run_step_index(run_id, step_index)
            await runs_service.update_run_waiting(
                run_id,
                result.wait_until or datetime.now(timezone.utc),
                result.wait_type or "delay",
            )
            return

        if result.status == "failed":
            await runs_service.log_step(
                run_id,
                step_index,
                "step_failed",
                input_data=action,
                output_data=result.output,
                error=result.error,
            )
            await runs_service.mark_run_failed(run_id, result.error or "Error desconocido")
            return

        await runs_service.log_step(
            run_id,
            step_index,
            "step_completed",
            input_data=action,
            output_data=result.output,
        )
        step_index += 1
        await runs_service.update_run_step_index(run_id, step_index)

    await runs_service.mark_run_completed(run_id)
