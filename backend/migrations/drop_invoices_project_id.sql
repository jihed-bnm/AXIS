-- Migration: drop the project_id column from invoices
-- The projects module was removed; this FK causes create_invoice to crash when
-- the projects table does not exist (PostgreSQL cannot resolve the FK constraint).
--
-- Run once against the target database:
--   psql -U <user> -d <dbname> -f backend/migrations/drop_invoices_project_id.sql
--
-- Safe to run multiple times (IF EXISTS guard).

ALTER TABLE invoices DROP COLUMN IF EXISTS project_id;
