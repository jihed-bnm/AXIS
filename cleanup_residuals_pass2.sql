-- cleanup_residuals_pass2.sql
-- Second-pass cleanup: merges and renames the 136 residual companies that survived
-- the first pass (cleanup_companies.sql) because strip-only normalization was
-- insufficient (letter-corruption injected by generate_raw_data.py:168).
--
-- SCOPE
--   Type 1 (64 rows): FK-repoint variant to existing canonical, then hard-delete.
--       - 29 original approved fuzzy merges (approved 2026-04-16)
--       - 15 Band 4 rows: letter-corrupted variants whose corrected name matched
--         an existing clean canonical (BNA BANK, STEG, Tunisair, GlobalNet,
--         Hexabyte, BIAT, confirmed 2026-04-17)
--       - 20 demotions: rows initially proposed as renames but whose target name
--         already exists as a clean canonical (Orange Tunisie, Attijari Bank, etc.)
--   Type 2 (72 rows): in-place name UPDATE only — no FK change, no delete.
--       - 64 clean-strip renames: stripping [*#!@] + collapsing whitespace
--         produces the correct final name
--       - 8 "looks-clean" Band 4 renames: strip result is correct, scored below
--         0.65 sim only because no matching clean company exists yet
--       - 2 manual renames: id=404 BN###A-Bank -> BNA-Bank,
--                           id=387 G***.Hamouda Digital -> G.Hamouda Digital
--
-- FK TABLES TOUCHED (same as first pass)
--   contacts, deals, invoices, activities
--   invoice_items is NOT touched (links via invoices.id, not company_id)
--
-- POST-STATE (expected)
--   0 companies with name ~ '[*#!@]' remaining (fully clean)
--   All FK tables have 0 orphaned references
--
-- USAGE
--   psql -U erp_user -d erp_db -f cleanup_residuals_pass2.sql
--
-- The transaction is left OPEN at the end (COMMIT is commented out).
-- Review all sanity-check output, then send:
--   COMMIT;    -- to apply
--   ROLLBACK;  -- to abort

BEGIN;

-- ============================================================================
-- 1. BUILD TYPE 1 MERGE MAP
--    All 64 (variant_id -> canonical_id) pairs, hard-coded from the
--    conflict-check analysis of 2026-04-17.
--    Canonical row is NEVER deleted.
-- ============================================================================

\echo ''
\echo '========================================================'
\echo '[1] Building Type 1 merge map (64 pairs) ...'
\echo '========================================================'

CREATE TEMP TABLE pass2_merge_map (
    variant_id   INTEGER NOT NULL,
    canonical_id INTEGER NOT NULL
);

INSERT INTO pass2_merge_map (variant_id, canonical_id) VALUES
-- ── Original 29 approved fuzzy merges (approved 2026-04-16) ─────────────────
(190,  94),
(538, 548),
(812, 804),
(736, 103),
(225,  78),
(668,  69),
(277,  94),
(297, 118),
(573, 542),
(664, 531),
(322, 203),
(582, 512),
(733, 508),
(561, 597),
( 90, 222),
(236, 203),
(344, 171),
(580, 115),
(651, 530),
(319,  97),
(467,  30),
(851, 520),
(384, 135),
(106,  57),
(292,  94),
(614,  78),
(456,  78),
(895,  78),
(393,   6),

-- ── Band 4 additions: 15 letter-corrupted rows, canonical confirmed 2026-04-17 ─
-- BNA Banek / BNA Beank  -> id=8 BNA BANK
(105,   8),
(676,   8),
-- STEeG / SToEG          -> id=51 STEG
(218,  51),
(852,  51),
-- Tuniosair / Tunisoair / Tounisair -> id=2 Tunisair
(220,   2),
(260,   2),
(688,   2),
-- GlobaolNet / GloebalNet / GlobaleNet / GolobalNet / GlobalNeot -> id=9 GlobalNet
(281,   9),
(338,   9),
(728,   9),
(813,   9),
(846,   9),
-- Hexaebyte / Hexaboyte  -> id=59 HEXABYTE
(325,  59),
(341,  59),
-- BIoAT                  -> id=16 BIAT
(448,  16),

-- ── Demotions: 20 rows initially proposed as renames, canonical already exists ─
-- Orangee Tunisie / Orangoe Tunisie -> id=35 (orange tunisie)
( 33,  35),
(280,  35),
-- STE eOueslati & Fils   -> id=99 STE Oueslati & Fils
(254,  99),
-- Topneet / Toopnet      -> id=11 (topnet)
(268,  11),
(740,  11),
-- Hexabytee              -> id=59 HEXABYTE
(311,  59),
-- Pooulina Group / Poulina oGroup -> id=6 (poulina group)
(316,   6),
(504,   6),
-- Ooredoo Tuonisie       -> id=40 OOREDOO TUNISIE
(359,  40),
-- La Poste Tuniosienne / La Poste Tunisoienne -> id=94 (la poste tunisienne)
(375,  94),
(672,  94),
-- Attoijari Bank / Attijari Baenk / Aettijari Bank -> id=69 ATTIJARI BANK
(400,  69),
(579,  69),
(634,  69),
-- GloobalNet             -> id=9 GlobalNet
(441,   9),
-- Tunisie eTelecom       -> id=44 Tunisie Telecom
(601,  44),
-- Imprimerie eEl Ittihad -> id=541 (imprimerie el ittihad)
(644, 541),
-- STE oMejri Informatique -> id=203 STE MEJRI INFORMATIQUE
(700, 203),
-- Cafoe Carthage         -> id=25 (cafe carthage)
(730,  25),
-- Deloice Danone         -> id=93 (delice danone)
(808,  93);

-- ── SANITY 1a: row count (must be 64) ────────────────────────────────────────
\echo ''
\echo '[SANITY 1a] Merge map row count (must be 64):'
SELECT COUNT(*) AS merge_map_rows FROM pass2_merge_map;

-- ── SANITY 1b: all variant_id rows must exist and be dirty ───────────────────
\echo ''
\echo '[SANITY 1b] Variant IDs not found in companies (must be 0):'
SELECT COUNT(*) AS missing_variants
FROM   pass2_merge_map m
WHERE  NOT EXISTS (
    SELECT 1 FROM companies c
    WHERE c.id = m.variant_id AND c.is_deleted = false
);

\echo ''
\echo '[SANITY 1b] Variant IDs that are NOT dirty (should be 0):'
SELECT m.variant_id, c.name
FROM   pass2_merge_map m
JOIN   companies c ON c.id = m.variant_id
WHERE  c.name !~ '[*#!@]'
  AND  c.is_deleted = false;

-- ── SANITY 1c: all canonical_id rows must exist and be clean ─────────────────
\echo ''
\echo '[SANITY 1c] Canonical IDs not found in companies (must be 0):'
SELECT COUNT(*) AS missing_canonicals
FROM   pass2_merge_map m
WHERE  NOT EXISTS (
    SELECT 1 FROM companies c
    WHERE c.id = m.canonical_id AND c.is_deleted = false
);

\echo ''
\echo '[SANITY 1c] Canonical IDs that are dirty (must be 0):'
SELECT m.canonical_id, c.name
FROM   pass2_merge_map m
JOIN   companies c ON c.id = m.canonical_id
WHERE  c.name ~ '[*#!@]'
  AND  c.is_deleted = false;

-- ── SANITY 1d: no variant is also a canonical in the same map ────────────────
\echo ''
\echo '[SANITY 1d] Variant appearing as its own canonical (must be 0):'
SELECT COUNT(*) AS self_merge
FROM   pass2_merge_map
WHERE  variant_id = canonical_id;

-- ── SANITY 1e: no canonical appears as a variant elsewhere in the map ─────────
\echo ''
\echo '[SANITY 1e] Canonical appearing as variant in another pair (must be 0):'
SELECT COUNT(*) AS canonical_as_variant
FROM   pass2_merge_map m1
WHERE  EXISTS (
    SELECT 1 FROM pass2_merge_map m2
    WHERE m2.variant_id = m1.canonical_id
);


-- ============================================================================
-- 2. REPOINT FOREIGN KEYS (Type 1 only)
--    Replace every variant_id with its canonical_id across all FK tables.
-- ============================================================================

\echo ''
\echo '========================================================'
\echo '[2] Repointing foreign keys for Type 1 merges ...'
\echo '========================================================'

\echo '[2a] contacts ...'
UPDATE contacts
SET    company_id = m.canonical_id
FROM   pass2_merge_map m
WHERE  contacts.company_id = m.variant_id;

\echo '[2b] deals ...'
UPDATE deals
SET    company_id = m.canonical_id
FROM   pass2_merge_map m
WHERE  deals.company_id = m.variant_id;

\echo '[2c] invoices ...'
UPDATE invoices
SET    company_id = m.canonical_id
FROM   pass2_merge_map m
WHERE  invoices.company_id = m.variant_id;

\echo '[2d] activities ...'
UPDATE activities
SET    company_id = m.canonical_id
FROM   pass2_merge_map m
WHERE  activities.company_id = m.variant_id;

-- ── SANITY 2: orphaned FKs after repoint (all must be 0) ─────────────────────
\echo ''
\echo '[SANITY 2] Orphaned FKs remaining after repoint (all must be 0):'
SELECT 'contacts'   AS tbl, COUNT(*) AS orphaned_fks
FROM   contacts
JOIN   pass2_merge_map m ON contacts.company_id = m.variant_id
UNION ALL
SELECT 'deals',      COUNT(*)
FROM   deals
JOIN   pass2_merge_map m ON deals.company_id = m.variant_id
UNION ALL
SELECT 'invoices',   COUNT(*)
FROM   invoices
JOIN   pass2_merge_map m ON invoices.company_id = m.variant_id
UNION ALL
SELECT 'activities', COUNT(*)
FROM   activities
JOIN   pass2_merge_map m ON activities.company_id = m.variant_id
ORDER BY tbl;


-- ============================================================================
-- 3. HARD-DELETE TYPE 1 VARIANTS
--    Safe because all FKs have been repointed in step 2.
-- ============================================================================

\echo ''
\echo '========================================================'
\echo '[3] Hard-deleting Type 1 variants (64 rows) ...'
\echo '========================================================'

DELETE FROM companies
WHERE id IN (SELECT variant_id FROM pass2_merge_map);

\echo ''
\echo '[SANITY 3] Rows deleted (must be 64):'
-- Infer from the map count; the DELETE itself will report affected rows above.
SELECT COUNT(*) AS merge_map_rows FROM pass2_merge_map;


-- ============================================================================
-- 4. TYPE 2 IN-PLACE RENAMES (72 rows)
--    UPDATE name only. No FK changes, no deletes.
--    Executed AFTER Type 1 deletes so any variant IDs that became FK targets
--    via repointing are already removed from the map.
-- ============================================================================

\echo ''
\echo '========================================================'
\echo '[4] Type 2 in-place renames (72 rows) ...'
\echo '========================================================'

-- ── Subset A: 64 clean-strip renames (incl. 2 manual targets 387, 404) ───────
UPDATE companies SET name = 'Cabinet Rekik & Associes SARL'       WHERE id = 124;
UPDATE companies SET name = 'B.d''Etudes Laabidi'                 WHERE id = 137;
UPDATE companies SET name = 'S.Khalfallah Consulting'             WHERE id = 144;
UPDATE companies SET name = 'C.Agrebi Conseil'                    WHERE id = 172;
UPDATE companies SET name = 'Bureau d''Etudes Ben Salah SUARL'    WHERE id = 173;
UPDATE companies SET name = 'G.Haddad Technologies'               WHERE id = 186;
UPDATE companies SET name = 'STE Bouzid Consulting SUARL'         WHERE id = 250;
UPDATE companies SET name = 'STE Oueslati & Fils SARL'            WHERE id = 284;
UPDATE companies SET name = 'La Poste Tunisienne SA'              WHERE id = 314;
UPDATE companies SET name = 'Tunisair SARL'                       WHERE id = 331;
UPDATE companies SET name = 'Topnet SARL'                         WHERE id = 349;
UPDATE companies SET name = 'G.Hamouda Digital'                   WHERE id = 387;   -- MANUAL
UPDATE companies SET name = 'BNA-Bank'                            WHERE id = 404;   -- MANUAL
UPDATE companies SET name = 'Banque de Tunisie SARL'              WHERE id = 421;
UPDATE companies SET name = 'Bureau d''Etudes Ben Salah SARL'     WHERE id = 424;
UPDATE companies SET name = 'Poulina Group SUARL'                 WHERE id = 425;
UPDATE companies SET name = 'Delice Danone SA'                    WHERE id = 430;
UPDATE companies SET name = 'Groupe Agrebi Technologies SUARL'    WHERE id = 433;
UPDATE companies SET name = 'Groupe Mansour Digital SARL'         WHERE id = 443;
UPDATE companies SET name = 'Delice Danone SARL'                  WHERE id = 449;
UPDATE companies SET name = 'STE Jlassei Consulting'              WHERE id = 451;
UPDATE companies SET name = 'Entreprise Chaabane SUARL'           WHERE id = 462;
UPDATE companies SET name = 'Cabinet Comptable Slim SARL'         WHERE id = 464;
UPDATE companies SET name = 'Banque de Tunisie SUARL'             WHERE id = 480;
UPDATE companies SET name = 'STE Khalfallah & Fils SARL'          WHERE id = 486;
UPDATE companies SET name = 'STE Bouzid Consulting SARL'          WHERE id = 503;
UPDATE companies SET name = 'Bureau d''Etudes Oueslati SARL'      WHERE id = 506;
UPDATE companies SET name = 'Centre Medical Bouzid SA'            WHERE id = 510;
UPDATE companies SET name = 'STE Gharbi Consulting SARL'          WHERE id = 511;
UPDATE companies SET name = 'BNA Bank SA'                         WHERE id = 568;
UPDATE companies SET name = 'STE Ferchiou Informatique SUARL'     WHERE id = 571;
UPDATE companies SET name = 'Topnet SA'                           WHERE id = 576;
UPDATE companies SET name = 'G.Trabelsi Technologies'             WHERE id = 587;
UPDATE companies SET name = 'S.Laabidi Consulting'                WHERE id = 588;
UPDATE companies SET name = 'STE Hamdi Consulting SUARL'          WHERE id = 600;
UPDATE companies SET name = 'CyberPark Elghazala SARL'            WHERE id = 604;
UPDATE companies SET name = 'Salon Coiffure Elegance SUARL'       WHERE id = 630;
UPDATE companies SET name = 'Pharmacie Al Amal SARL'              WHERE id = 638;
UPDATE companies SET name = 'Orange Tunisie SA'                   WHERE id = 645;
UPDATE companies SET name = 'Entreprise Haddad SUARL'             WHERE id = 654;
UPDATE companies SET name = 'Hexabyte SARL'                       WHERE id = 671;
UPDATE companies SET name = 'Clinique-Dentaire-Dr-Mrad'           WHERE id = 707;
UPDATE companies SET name = 'CyberPark Elghazala SUARL'           WHERE id = 714;
UPDATE companies SET name = 'Bureau d''Etudes Bouzid SARL'        WHERE id = 738;
UPDATE companies SET name = 'GlobalNet SA'                        WHERE id = 750;
UPDATE companies SET name = 'Hexabyte SA'                         WHERE id = 755;
UPDATE companies SET name = 'STE Laabidi Consulting SARL'         WHERE id = 768;
UPDATE companies SET name = 'STE Hamdi Consulting SARL'           WHERE id = 780;
UPDATE companies SET name = 'S.Gharbi Consulting'                 WHERE id = 782;
UPDATE companies SET name = 'Cabinet Agrebi Conseil SUARL'        WHERE id = 811;
UPDATE companies SET name = 'Groupe Hamdi Digital SUARL'          WHERE id = 819;
UPDATE companies SET name = 'Groupe Zouari Digital SARL'          WHERE id = 821;
UPDATE companies SET name = 'Studio Photo Memories SUARL'         WHERE id = 825;
UPDATE companies SET name = 'Ooredoo Tunisie SA'                  WHERE id = 831;
UPDATE companies SET name = 'STE Ben Salah Consulting SUARL'      WHERE id = 836;
UPDATE companies SET name = 'STE Oueslati & Fils SUARL'           WHERE id = 842;
UPDATE companies SET name = 'S.Chaabane Solutions'                WHERE id = 853;
UPDATE companies SET name = 'S.Khalfallah & Fils'                 WHERE id = 858;
UPDATE companies SET name = 'Bureau d''Etudes Laabidi SUARL'      WHERE id = 865;
UPDATE companies SET name = 'STE Ben Salah Consulting SARL'       WHERE id = 876;
UPDATE companies SET name = 'STE Belhadj Consulting SARL'         WHERE id = 881;
UPDATE companies SET name = 'STE Khalfallah Consulting SARL'      WHERE id = 883;
UPDATE companies SET name = 'STE Laabidi Consulting SUARL'        WHERE id = 898;
UPDATE companies SET name = 'STE Khalfallah & Fils SUARL'         WHERE id = 902;

-- ── Subset B: 8 looks-clean Band 4 renames (strip correct, low sim score) ────
UPDATE companies SET name = 'R.Le Mediterranee'   WHERE id = 262;
UPDATE companies SET name = 'CNSS SARL'           WHERE id = 310;
UPDATE companies SET name = 'BIAT SARL'           WHERE id = 333;
UPDATE companies SET name = 'Tunisair SUARL'      WHERE id = 383;
UPDATE companies SET name = 'CNAM SUARL'          WHERE id = 445;
UPDATE companies SET name = 'UIB SARL'            WHERE id = 468;
UPDATE companies SET name = 'STEG SARL'           WHERE id = 849;
UPDATE companies SET name = 'CNAM SA'             WHERE id = 872;

-- ── SANITY 4a: verify each renamed row now matches the intended value ─────────
\echo ''
\echo '[SANITY 4a] Spot-check: named rows that still contain [*#!@] after rename (must be 0):'
SELECT id, name
FROM   companies
WHERE  id IN (
    124,137,144,172,173,186,250,262,284,310,314,331,333,349,383,387,404,
    421,424,425,430,433,443,445,449,451,462,464,468,480,486,503,506,510,
    511,568,571,576,587,588,600,604,630,638,645,654,671,707,714,738,750,
    755,768,780,782,811,819,821,825,831,836,842,849,853,858,865,872,876,
    881,883,898,902
)
  AND name ~ '[*#!@]'
  AND is_deleted = false;


-- ============================================================================
-- 5. FINAL SANITY CHECKS
-- ============================================================================

\echo ''
\echo '========================================================'
\echo '[5] Final sanity checks ...'
\echo '========================================================'

-- ── SANITY 5a: no dirty companies remaining (must be 0) ──────────────────────
\echo ''
\echo '[SANITY 5a] Companies with [*#!@] remaining (must be 0):'
SELECT COUNT(*) AS remaining_dirty
FROM   companies
WHERE  name ~ '[*#!@]'
  AND  is_deleted = false;

-- ── Show any survivors for diagnosis ─────────────────────────────────────────
\echo ''
\echo '[SANITY 5a detail] Surviving dirty rows (should be empty):'
SELECT id, name
FROM   companies
WHERE  name ~ '[*#!@]'
  AND  is_deleted = false
ORDER  BY id;

-- ── SANITY 5b: total active companies ────────────────────────────────────────
\echo ''
\echo '[SANITY 5b] Total active companies after cleanup (informational):'
SELECT COUNT(*) AS total_active FROM companies WHERE is_deleted = false;

-- ── SANITY 5c: zero orphaned FKs anywhere ────────────────────────────────────
\echo ''
\echo '[SANITY 5c] Orphaned FKs (company_id references deleted/missing rows; must be 0):'
SELECT 'contacts'   AS tbl, COUNT(*) AS orphaned
FROM   contacts c
WHERE  NOT EXISTS (SELECT 1 FROM companies co WHERE co.id = c.company_id AND co.is_deleted = false)
UNION ALL
SELECT 'deals',      COUNT(*)
FROM   deals d
WHERE  NOT EXISTS (SELECT 1 FROM companies co WHERE co.id = d.company_id AND co.is_deleted = false)
UNION ALL
SELECT 'invoices',   COUNT(*)
FROM   invoices i
WHERE  NOT EXISTS (SELECT 1 FROM companies co WHERE co.id = i.company_id AND co.is_deleted = false)
UNION ALL
SELECT 'activities', COUNT(*)
FROM   activities a
WHERE  NOT EXISTS (SELECT 1 FROM companies co WHERE co.id = a.company_id AND co.is_deleted = false)
ORDER BY tbl;

-- ── SANITY 5d: spot-check known entities ─────────────────────────────────────
\echo ''
\echo '[SANITY 5d] BNA family (expect: BNA BANK id=8, BNA-Bank id=404, BNA Bank SA id=568):'
SELECT id, name FROM companies
WHERE name ILIKE '%bna%' AND is_deleted = false ORDER BY id;

\echo ''
\echo '[SANITY 5d] Orange Tunisie family (expect clean suffix variants only):'
SELECT id, name FROM companies
WHERE name ILIKE '%orange%tunisi%' AND is_deleted = false ORDER BY id;

\echo ''
\echo '[SANITY 5d] Poulina family (expect clean suffix variants only):'
SELECT id, name FROM companies
WHERE name ILIKE '%poulina%' AND is_deleted = false ORDER BY id;

\echo ''
\echo '[SANITY 5d] Attijari family (expect clean suffix variants only):'
SELECT id, name FROM companies
WHERE name ILIKE '%attijari%' AND is_deleted = false ORDER BY id;

\echo ''
\echo '[SANITY 5d] G.Hamouda Digital (id=387, renamed from G***.Hamouda Digital):'
SELECT id, name FROM companies WHERE id = 387 AND is_deleted = false;

\echo ''
\echo '[SANITY 5d] BNA-Bank (id=404, renamed from BN###A-Bank):'
SELECT id, name FROM companies WHERE id = 404 AND is_deleted = false;


-- ============================================================================
-- TRANSACTION IS OPEN -- review all sanity output above, then:
--   COMMIT;    to apply
--   ROLLBACK;  to abort
-- ============================================================================

\echo ''
\echo '========================================================'
\echo 'Transaction is OPEN.'
\echo 'All sanity checks must show 0 dirty rows and 0 orphaned FKs.'
\echo 'Send COMMIT; to apply or ROLLBACK; to abort.'
\echo '========================================================'

-- COMMIT;
