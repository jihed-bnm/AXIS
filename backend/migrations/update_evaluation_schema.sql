-- ────────────────────────────────────────────────────────────────────────────
-- Migration: update_evaluation_schema.sql
-- Adds multi-metric scoring columns to axis_exchange_evaluations.
-- Run manually AFTER Phase 1 is confirmed working:
--   psql -h <host> -U <user> -d <db> -f update_evaluation_schema.sql
-- All new columns are NULLABLE so existing rows are unaffected.
-- ────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.axis_exchange_evaluations
    ADD COLUMN IF NOT EXISTS context_relevance   NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS retrieval_precision NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS hit_rate            NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS reciprocal_rank     NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS ndcg                NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS task_adherence      NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS tool_call_accuracy  NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS intent_resolution   NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS overall_score       NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS evaluation_notes    TEXT;

-- Add CHECK constraints in a second pass (safe with IF NOT EXISTS columns above)
ALTER TABLE public.axis_exchange_evaluations
    ADD CONSTRAINT IF NOT EXISTS chk_context_relevance   CHECK (context_relevance   IS NULL OR (context_relevance   >= 0 AND context_relevance   <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_retrieval_precision CHECK (retrieval_precision IS NULL OR (retrieval_precision >= 0 AND retrieval_precision <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_hit_rate            CHECK (hit_rate            IS NULL OR (hit_rate            >= 0 AND hit_rate            <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_reciprocal_rank     CHECK (reciprocal_rank     IS NULL OR (reciprocal_rank     >= 0 AND reciprocal_rank     <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_ndcg                CHECK (ndcg                IS NULL OR (ndcg                >= 0 AND ndcg                <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_task_adherence      CHECK (task_adherence      IS NULL OR (task_adherence      >= 0 AND task_adherence      <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_tool_call_accuracy  CHECK (tool_call_accuracy  IS NULL OR (tool_call_accuracy  >= 0 AND tool_call_accuracy  <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_intent_resolution   CHECK (intent_resolution   IS NULL OR (intent_resolution   >= 0 AND intent_resolution   <= 1)),
    ADD CONSTRAINT IF NOT EXISTS chk_overall_score       CHECK (overall_score       IS NULL OR (overall_score       >= 0 AND overall_score       <= 1));

COMMENT ON COLUMN public.axis_exchange_evaluations.context_relevance
    IS 'RAG: relevance of retrieved context to user query. NULL when RAG was not used.';
COMMENT ON COLUMN public.axis_exchange_evaluations.retrieval_precision
    IS 'RAG: fraction of retrieved chunks actually useful. NULL when RAG was not used.';
COMMENT ON COLUMN public.axis_exchange_evaluations.hit_rate
    IS 'RAG: binary (1.0 or 0.0) — at least one relevant doc retrieved. NULL when RAG not used.';
COMMENT ON COLUMN public.axis_exchange_evaluations.reciprocal_rank
    IS 'RAG: 1/rank of first relevant chunk. NULL when RAG not used.';
COMMENT ON COLUMN public.axis_exchange_evaluations.ndcg
    IS 'RAG: Normalized Discounted Cumulative Gain for chunk ranking. NULL when RAG not used.';
COMMENT ON COLUMN public.axis_exchange_evaluations.task_adherence
    IS 'Agent: did the agent complete exactly what the user requested.';
COMMENT ON COLUMN public.axis_exchange_evaluations.tool_call_accuracy
    IS 'Agent: correct tool called with correct parameters.';
COMMENT ON COLUMN public.axis_exchange_evaluations.intent_resolution
    IS 'Agent: did the agent correctly interpret user intent.';
COMMENT ON COLUMN public.axis_exchange_evaluations.overall_score
    IS 'Weighted: task_adherence(0.25)+tool_call_accuracy(0.20)+intent_resolution(0.20)+context_relevance(0.15)+retrieval_precision(0.10)+hit_rate(0.03)+reciprocal_rank(0.03)+ndcg(0.04). Reweighted to 1.0 when RAG metrics are NULL.';
COMMENT ON COLUMN public.axis_exchange_evaluations.evaluation_notes
    IS 'Judge justification for each metric, semicolon-separated.';

-- ── Session-level evaluation capture columns ──────────────────────────────────
-- NOTE: These are also auto-created at server startup (ALTER TABLE IF NOT EXISTS),
-- so this block is a no-op after first server start.

ALTER TABLE public.sessions
    ADD COLUMN IF NOT EXISTS tool_calls  TEXT,
    ADD COLUMN IF NOT EXISTS rag_context TEXT;

COMMENT ON COLUMN public.sessions.tool_calls
    IS 'JSON list of tool calls made during the last exchange: [{"tool":str,"params":{}}].';
COMMENT ON COLUMN public.sessions.rag_context
    IS 'RAG context text injected before the last agent run. NULL when no RAG retrieval occurred.';
