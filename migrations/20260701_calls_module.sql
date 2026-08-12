CREATE TABLE IF NOT EXISTS public.calls (
  id bigserial PRIMARY KEY,
  call_id varchar(255) NOT NULL UNIQUE,
  direction varchar(10),
  caller_number varchar(32),
  callee_number varchar(32),
  agent_extension varchar(32),
  client_id bigint REFERENCES clients(id),
  started_at timestamp NOT NULL,
  duration_seconds int,
  audio_path text,
  audio_status varchar(20) DEFAULT 'pending',
  transcript text,
  transcript_status varchar(20) DEFAULT 'pending',
  ai_category varchar(20),
  ai_result jsonb,
  ai_department text,
  ai_priority varchar(8),
  ai_assignee_result jsonb,
  ai_assignee varchar(255),
  queue_status varchar(24) DEFAULT 'queued_ingest',
  sent_to_cts_at timestamp,
  cts_send_attempts int DEFAULT 0,
  created_at timestamp DEFAULT now(),
  updated_at timestamp DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_calls_client ON public.calls(client_id);
CREATE INDEX IF NOT EXISTS idx_calls_started ON public.calls(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_queue_status ON public.calls(queue_status);
