CREATE SCHEMA analytics;
CREATE TABLE analytics.sales (tenant text NOT NULL, day date NOT NULL, product text NOT NULL, region text NOT NULL, amount numeric(12,2) NOT NULL);
INSERT INTO analytics.sales VALUES
('report_a','2025-01-01','tea','north',100),
('report_a','2025-01-02','tea','south',150),
('report_a','2025-01-03','coffee','north',200),
('report_b','2025-01-01','tea','north',9999);
CREATE ROLE report_a LOGIN PASSWORD 'demo-a' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE report_b LOGIN PASSWORD 'demo-b' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
REVOKE ALL ON DATABASE analytics FROM PUBLIC;
GRANT CONNECT ON DATABASE analytics TO report_a,report_b;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA analytics TO report_a,report_b;
GRANT SELECT(day,product,region,amount) ON analytics.sales TO report_a,report_b;
ALTER TABLE analytics.sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.sales FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_policy ON analytics.sales TO report_a,report_b USING (tenant=current_user);
ALTER ROLE report_a SET default_transaction_read_only=on;
ALTER ROLE report_b SET default_transaction_read_only=on;
ALTER ROLE report_a SET statement_timeout='1s';
ALTER ROLE report_b SET statement_timeout='1s';
ALTER ROLE report_a SET lock_timeout='250ms';
ALTER ROLE report_b SET lock_timeout='250ms';
ALTER ROLE report_a SET idle_in_transaction_session_timeout='2s';
ALTER ROLE report_b SET idle_in_transaction_session_timeout='2s';
ALTER ROLE report_a SET temp_file_limit='1024kB';
ALTER ROLE report_b SET temp_file_limit='1024kB';
ALTER ROLE report_a SET work_mem='1MB';
ALTER ROLE report_b SET work_mem='1MB';
