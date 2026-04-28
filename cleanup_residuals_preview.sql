-- cleanup_residuals_preview.sql
-- READ-ONLY investigation. Does not modify anything.
--
-- Finds proposed (residual → canonical) merge pairs for the 136 letter-corruption
-- survivors that were not reachable by strip-only normalization in cleanup_companies.sql.
--
-- A "residual" is any company where name ~ '[*#!@]' (still dirty after first pass).
-- A "canonical candidate" is any company where name !~ '[*#!@]' (already clean).
--
-- For each residual, we find the single best-matching clean company by
-- pg_trgm similarity on lowercased names. Only pairs scoring >= 0.70 are shown.
-- Pairs scoring < 0.70 have no clean partner above threshold and appear separately.
--
-- IMPORTANT: similarity is case-insensitive but NOT normalization-aware.
-- "BNA Bea!!!nk" vs "BNA BANK": strip-then-compare would give "bna beank" vs
-- "bna bank" — trigram similarity catches the residual character overlap.
--
-- Review every proposed merge before approving. Pay attention to:
--   - SA / SARL / SUARL suffixes: legally distinct entities, keep separate
--   - Abbreviation expansions: "C.CNAM" vs "CNAM" may be different entities
--   - sim < 0.80: treat as suspicious, requires explicit approval
--
-- USAGE (read-only, no transaction needed):
--   psql -U erp_user -d erp_db -f cleanup_residuals_preview.sql

-- Ensure pg_trgm is available (idempotent, read-only effect).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\echo ''
\echo '════════════════════════════════════════════════════════'
\echo '[1] Residual count (the 136 dirty survivors)'
\echo '════════════════════════════════════════════════════════'

SELECT COUNT(*) AS residual_count
FROM companies
WHERE name ~ '[*#!@]'
AND   is_deleted = false;

\echo ''
\echo '════════════════════════════════════════════════════════'
\echo '[2] Proposed merges: residual → best clean canonical'
\echo '    sim >= 0.70 | ordered by sim DESC, residual_id'
\echo '    Review EVERY row before approving any merge.'
\echo '════════════════════════════════════════════════════════'

WITH residuals AS (
    -- The 136 dirty survivors
    SELECT id, name
    FROM   companies
    WHERE  name ~ '[*#!@]'
    AND    is_deleted = false
),
clean_canonicals AS (
    -- Companies already clean after the first pass
    SELECT id, name
    FROM   companies
    WHERE  name !~ '[*#!@]'
    AND    is_deleted = false
),
best_match AS (
    -- For each residual, find the single clean company with the highest similarity.
    -- DISTINCT ON keeps only the top match per residual.
    SELECT DISTINCT ON (r.id)
        r.id                                                     AS residual_id,
        r.name                                                   AS residual_name,
        c.id                                                     AS canonical_id,
        c.name                                                   AS canonical_name,
        round(similarity(LOWER(r.name), LOWER(c.name))::numeric, 3) AS sim
    FROM   residuals r
    JOIN   clean_canonicals c
           ON similarity(LOWER(r.name), LOWER(c.name)) >= 0.70
    ORDER  BY r.id, similarity(LOWER(r.name), LOWER(c.name)) DESC
)
SELECT
    residual_id,
    residual_name,
    canonical_id,
    canonical_name,
    sim
FROM   best_match
ORDER  BY sim DESC, residual_id;

\echo ''
\echo '════════════════════════════════════════════════════════'
\echo '[3] Residuals with NO clean match >= 0.70'
\echo '    These have no safe fuzzy partner — decide per case.'
\echo '════════════════════════════════════════════════════════'

WITH residuals AS (
    SELECT id, name
    FROM   companies
    WHERE  name ~ '[*#!@]'
    AND    is_deleted = false
),
clean_canonicals AS (
    SELECT id, name
    FROM   companies
    WHERE  name !~ '[*#!@]'
    AND    is_deleted = false
),
has_match AS (
    SELECT DISTINCT r.id
    FROM   residuals r
    JOIN   clean_canonicals c
           ON similarity(LOWER(r.name), LOWER(c.name)) >= 0.70
)
SELECT r.id AS residual_id, r.name AS residual_name
FROM   residuals r
WHERE  r.id NOT IN (SELECT id FROM has_match)
ORDER  BY r.name;

\echo ''
\echo '[END] Read-only preview complete. No changes made.'
