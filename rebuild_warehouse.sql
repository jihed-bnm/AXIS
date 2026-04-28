-- rebuild_warehouse.sql
-- Rebuilds all four warehouse tables from the clean operational DB (public.*).
-- Source: public.companies / deals / invoices / activities (is_deleted = false only).
-- No ETL, no CSVs. Pure SQL denormalization.
--
-- Run with:
--   PGPASSWORD=erp_pass psql -U erp_user -d erp_db -h localhost -p 5432 -f rebuild_warehouse.sql
--
-- Review sanity-check output, then un-comment COMMIT and re-run.

BEGIN;

-- ── 1. Truncate all four warehouse tables ────────────────────────────────────
TRUNCATE
    warehouse.dim_client,
    warehouse.fact_deals,
    warehouse.fact_revenue,
    warehouse.fact_activities
    RESTART IDENTITY CASCADE;


-- ── 2. dim_client ← public.companies (active rows only) ─────────────────────
-- client_id is SERIAL — omitted, sequence auto-assigns.
INSERT INTO warehouse.dim_client (
    company_name,
    phone,
    email,
    city,
    country,
    industry,
    status,
    created_date,
    source_file,
    loaded_at
)
SELECT
    c.name                  AS company_name,
    c.phone,
    c.email,
    c.city,
    c.country,
    c.industry,
    c.status,
    c.created_at::date      AS created_date,
    'operational'           AS source_file,
    NOW()                   AS loaded_at
FROM public.companies c
WHERE c.is_deleted = false;


-- ── 3. fact_deals ← public.deals + public.companies ─────────────────────────
-- deal_id is SERIAL — omitted.
-- assigned_to: public.deals has no user FK; set NULL.
-- deal_ref format: DEAL-000001  (6-digit zero-padded deal id)
-- deal_size thresholds: <5k Small, <20k Medium, <100k Large, else Enterprise
-- quarter format: Q2 2024
INSERT INTO warehouse.fact_deals (
    deal_ref,
    company_name,
    title,
    stage,
    status,
    value_tnd,
    probability,
    deal_size_category,
    quarter,
    days_to_close,
    created_date,
    closed_date,
    assigned_to,
    loaded_at
)
SELECT
    'DEAL-' || LPAD(d.id::text, 6, '0')                            AS deal_ref,
    c.name                                                           AS company_name,
    d.title,
    d.stage,
    d.status,
    d.value::numeric(14,2)                                          AS value_tnd,
    d.probability::numeric(5,2)                                     AS probability,
    CASE
        WHEN d.value IS NULL   THEN 'Unknown'
        WHEN d.value < 5000    THEN 'Small'
        WHEN d.value < 20000   THEN 'Medium'
        WHEN d.value < 100000  THEN 'Large'
        ELSE                        'Enterprise'
    END                                                              AS deal_size_category,
    'Q' || EXTRACT(QUARTER FROM d.created_at)::int
        || ' ' || EXTRACT(YEAR   FROM d.created_at)::int            AS quarter,
    CASE
        WHEN d.closed_at IS NOT NULL
        THEN (d.closed_at::date - d.created_at::date)
    END                                                              AS days_to_close,
    d.created_at::date                                               AS created_date,
    d.closed_at::date                                                AS closed_date,
    NULL                                                             AS assigned_to,
    NOW()                                                            AS loaded_at
FROM public.deals d
JOIN public.companies c
    ON c.id = d.company_id
    AND c.is_deleted = false
WHERE d.is_deleted = false;


-- ── 4. fact_revenue ← public.invoices + public.companies ────────────────────
-- revenue_id is SERIAL — omitted.
-- amount_paid: full total when paid, 0 otherwise (no partial-payment field in operational).
-- is_overdue: due_date in the past AND not paid/cancelled.
-- days_outstanding: 0 for paid/cancelled, else CURRENT_DATE - issue_date.
INSERT INTO warehouse.fact_revenue (
    invoice_number,
    company_name,
    invoice_date,
    due_date,
    subtotal,
    tax_amount,
    total_amount,
    amount_paid,
    status,
    payment_delay_days,
    is_overdue,
    days_outstanding,
    loaded_at
)
SELECT
    i.invoice_number,
    c.name                                                           AS company_name,
    i.issue_date                                                     AS invoice_date,
    i.due_date,
    i.subtotal::numeric(14,2)                                       AS subtotal,
    i.tax_amount::numeric(14,2)                                     AS tax_amount,
    i.total::numeric(14,2)                                          AS total_amount,
    CASE
        WHEN i.status = 'paid' THEN i.total::numeric(14,2)
        ELSE 0
    END                                                              AS amount_paid,
    i.status,
    CASE
        WHEN i.paid_at IS NOT NULL
        THEN (i.paid_at::date - i.issue_date)
    END                                                              AS payment_delay_days,
    (i.due_date < CURRENT_DATE
        AND i.status NOT IN ('paid', 'cancelled'))                  AS is_overdue,
    CASE
        WHEN i.status NOT IN ('paid', 'cancelled')
        THEN (CURRENT_DATE - i.issue_date)
        ELSE 0
    END                                                              AS days_outstanding,
    NOW()                                                            AS loaded_at
FROM public.invoices i
JOIN public.companies c
    ON c.id = i.company_id
    AND c.is_deleted = false
WHERE i.is_deleted = false;


-- ── 5. fact_activities ← public.activities + companies + contacts + users ────
-- activity_id is SERIAL — omitted.
-- source_id format: ACT-0000001  (7-digit zero-padded activity id)
-- contact_name: LEFT JOIN public.contacts via contact_id (mostly NULL in operational).
-- assigned_to: LEFT JOIN public.users via user_id (username field).
-- duration_min: not stored in operational activities → NULL.
-- deal_reference: no deal FK on activities → NULL.
-- outcome: keyword-derived from description (mirrors ETL churn/positive logic).
-- churn_signal / positive_signal: same keyword set, set as boolean.
-- activity_type: normalised from free-form operational type field.
INSERT INTO warehouse.fact_activities (
    source_id,
    company_name,
    contact_name,
    activity_type,
    activity_date,
    duration_min,
    outcome,
    churn_signal,
    positive_signal,
    description,
    assigned_to,
    deal_reference,
    loaded_at
)
SELECT
    'ACT-' || LPAD(a.id::text, 7, '0')                             AS source_id,
    c.name                                                           AS company_name,
    CASE
        WHEN ct.id IS NOT NULL
        THEN ct.first_name || ' ' || ct.last_name
    END                                                              AS contact_name,
    CASE LOWER(a.type)
        WHEN 'call'        THEN 'Appel'
        WHEN 'appel'       THEN 'Appel'
        WHEN 'email'       THEN 'Email'
        WHEN 'courriel'    THEN 'Email'
        WHEN 'meeting'     THEN 'Réunion'
        WHEN 'reunion'     THEN 'Réunion'
        WHEN 'réunion'     THEN 'Réunion'
        WHEN 'task'        THEN 'Task'
        WHEN 'note'        THEN 'Note'
        WHEN 'demo'        THEN 'Démo'
        WHEN 'démo'        THEN 'Démo'
        WHEN 'visit'       THEN 'Visite'
        WHEN 'visite'      THEN 'Visite'
        WHEN 'relance'     THEN 'Relance'
        WHEN 'follow-up'   THEN 'Relance'
        WHEN 'support'     THEN 'Support'
        WHEN 'formation'   THEN 'Formation'
        WHEN 'training'    THEN 'Formation'
        ELSE INITCAP(a.type)
    END                                                              AS activity_type,
    COALESCE(
        a.done_at::date,
        a.due_date::date,
        a.created_at::date
    )                                                                AS activity_date,
    NULL::integer                                                    AS duration_min,
    -- outcome: negative > positive > neutral  (negative wins if both match)
    CASE
        WHEN a.description ILIKE '%insatisfait%'
          OR a.description ILIKE '%concurrent%'
          OR a.description ILIKE '%resilie%'
          OR a.description ILIKE '%résilié%'
          OR a.description ILIKE '%annule%'
          OR a.description ILIKE '%annulé%'
          OR a.description ILIKE '%probleme%'
          OR a.description ILIKE '%problème%'
          OR a.description ILIKE '%plainte%'
          OR a.description ILIKE '%bloque%'
          OR a.description ILIKE '%bloqué%'
          OR a.description ILIKE '%pas satisfait%'
          OR a.description ILIKE '%decu%'
          OR a.description ILIKE '%déçu%'
          OR a.description ILIKE '%qualite trop%'
          OR a.description ILIKE '%qualité trop%'
          OR a.description ILIKE '%tarif trop%'
        THEN 'negative'
        WHEN a.description ILIKE '%satisfait%'
          OR a.description ILIKE '%excellent%'
          OR a.description ILIKE '%renouvellement%'
          OR a.description ILIKE '%recommande%'
          OR a.description ILIKE '%recommandé%'
          OR a.description ILIKE '%signe%'
          OR a.description ILIKE '%signé%'
          OR a.description ILIKE '%valide%'
          OR a.description ILIKE '%validé%'
          OR a.description ILIKE '%accord%'
          OR a.description ILIKE '%ravi%'
          OR a.description ILIKE '%confiant%'
          OR a.description ILIKE '%upsell%'
          OR a.description ILIKE '%croissance%'
          OR a.description ILIKE '%partenariat%'
          OR a.description ILIKE '%fidelite%'
          OR a.description ILIKE '%fidélité%'
          OR a.description ILIKE '%expansion%'
        THEN 'positive'
        ELSE 'neutral'
    END                                                              AS outcome,
    -- churn_signal boolean
    (
        a.description ILIKE '%insatisfait%'
        OR a.description ILIKE '%concurrent%'
        OR a.description ILIKE '%resilie%'
        OR a.description ILIKE '%résilié%'
        OR a.description ILIKE '%annule%'
        OR a.description ILIKE '%annulé%'
        OR a.description ILIKE '%probleme%'
        OR a.description ILIKE '%problème%'
        OR a.description ILIKE '%plainte%'
        OR a.description ILIKE '%bloque%'
        OR a.description ILIKE '%bloqué%'
        OR a.description ILIKE '%pas satisfait%'
        OR a.description ILIKE '%decu%'
        OR a.description ILIKE '%déçu%'
        OR a.description ILIKE '%qualite trop%'
        OR a.description ILIKE '%qualité trop%'
        OR a.description ILIKE '%tarif trop%'
    )                                                                AS churn_signal,
    -- positive_signal boolean
    (
        a.description ILIKE '%satisfait%'
        OR a.description ILIKE '%excellent%'
        OR a.description ILIKE '%renouvellement%'
        OR a.description ILIKE '%recommande%'
        OR a.description ILIKE '%recommandé%'
        OR a.description ILIKE '%signe%'
        OR a.description ILIKE '%signé%'
        OR a.description ILIKE '%valide%'
        OR a.description ILIKE '%validé%'
        OR a.description ILIKE '%accord%'
        OR a.description ILIKE '%ravi%'
        OR a.description ILIKE '%confiant%'
        OR a.description ILIKE '%upsell%'
        OR a.description ILIKE '%croissance%'
        OR a.description ILIKE '%partenariat%'
        OR a.description ILIKE '%fidelite%'
        OR a.description ILIKE '%fidélité%'
        OR a.description ILIKE '%expansion%'
    )                                                                AS positive_signal,
    a.description,
    u.username                                                       AS assigned_to,
    NULL                                                             AS deal_reference,
    NOW()                                                            AS loaded_at
FROM public.activities a
JOIN public.companies c
    ON c.id = a.company_id
    AND c.is_deleted = false
LEFT JOIN public.contacts ct
    ON ct.id = a.contact_id
    AND ct.is_deleted = false
LEFT JOIN public.users u
    ON u.id = a.user_id;


-- ── 6. Sanity checks ─────────────────────────────────────────────────────────
-- Expected: dim_client=359, fact_deals~7713, fact_revenue~2226, fact_activities~47052

SELECT 'dim_client'      AS tbl, COUNT(*) AS rows FROM warehouse.dim_client
UNION ALL
SELECT 'fact_deals'      AS tbl, COUNT(*) AS rows FROM warehouse.fact_deals
UNION ALL
SELECT 'fact_revenue'    AS tbl, COUNT(*) AS rows FROM warehouse.fact_revenue
UNION ALL
SELECT 'fact_activities' AS tbl, COUNT(*) AS rows FROM warehouse.fact_activities;

-- Pollution check: all four company_name columns must return 0 dirty rows
SELECT 'dim_client_dirty'       AS check_name, COUNT(*) AS dirty
    FROM warehouse.dim_client      WHERE company_name ~ '[*#!@]'
UNION ALL
SELECT 'fact_deals_dirty'       AS check_name, COUNT(*) AS dirty
    FROM warehouse.fact_deals      WHERE company_name ~ '[*#!@]'
UNION ALL
SELECT 'fact_revenue_dirty'     AS check_name, COUNT(*) AS dirty
    FROM warehouse.fact_revenue    WHERE company_name ~ '[*#!@]'
UNION ALL
SELECT 'fact_activities_dirty'  AS check_name, COUNT(*) AS dirty
    FROM warehouse.fact_activities WHERE company_name ~ '[*#!@]';

-- BNA spot-check in dim_client (expect 4 rows: BNA BANK, BNA Bank SUARL, BNA-Bank, BNA Bank SA)
SELECT client_id, company_name
FROM warehouse.dim_client
WHERE company_name ILIKE '%BNA%'
ORDER BY company_name;

COMMIT;
