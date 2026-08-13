CREATE OR REPLACE FUNCTION notify_outbox_event_created()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify(
        'xingestion_outbox_events',
        json_build_object(
            'event_id', NEW.event_id,
            'task_id', NEW.task_id,
            'created_at', NEW.created_at
        )::text
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_outbox_event_created_notify ON outbox_events;

CREATE TRIGGER trg_outbox_event_created_notify
AFTER INSERT ON outbox_events
FOR EACH ROW
EXECUTE FUNCTION notify_outbox_event_created();
