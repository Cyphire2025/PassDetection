"""Canonical PostgreSQL16 expressions from the migrated indexes.

PostgreSQL expands implicit casts and concat associativity. Keeping its exact
representation allows Alembic to compare expressions without suppressing index
drift. Runtime expression/migration parity and real planner use are tested.
"""

PASSPORT_SEARCH_SQL = "lower((((((((((((((((((COALESCE(client_name, ''::character varying)::text || '\x1f'::text) || COALESCE(client_email, ''::character varying)::text) || '\x1f'::text) || COALESCE(client_phone, ''::character varying)::text) || '\x1f'::text) || COALESCE(departure_city, ''::character varying)::text) || '\x1f'::text) || COALESCE((extracted_fields ->> 'passport_number'::text)::character varying, ''::character varying)::text) || '\x1f'::text) || COALESCE((confirmed_fields ->> 'passport_number'::text)::character varying, ''::character varying)::text) || '\x1f'::text) || COALESCE((extracted_fields ->> 'surname'::text)::character varying, ''::character varying)::text) || '\x1f'::text) || COALESCE((confirmed_fields ->> 'surname'::text)::character varying, ''::character varying)::text) || '\x1f'::text) || COALESCE((extracted_fields ->> 'given_names'::text)::character varying, ''::character varying)::text) || '\x1f'::text) || COALESCE((confirmed_fields ->> 'given_names'::text)::character varying, ''::character varying)::text)"
GROUP_SEARCH_SQL = "lower((COALESCE(name, ''::character varying)::text || '\x1f'::text) || COALESCE(destination, ''::character varying)::text)"
