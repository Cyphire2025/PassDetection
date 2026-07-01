"""client groups

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-27 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # We are dropping upload_links and recreating as client_groups
    # for simplicity in this phase to accommodate the new business logic.
    op.drop_table('passport_submissions')
    op.drop_table('upload_links')
    
    op.execute("DROP TYPE IF EXISTS upload_link_status_enum")
    op.execute("DROP TYPE IF EXISTS submission_status_enum")

    # Recreate the group status enum
    op.execute("CREATE TYPE group_status_enum AS ENUM ('active', 'closed', 'archived')")
    
    op.create_table('client_groups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('token', sa.String(length=128), nullable=False),
        sa.Column('agency_id', sa.UUID(), nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'closed', 'archived', name='group_status_enum', create_type=False), nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_client_groups_token'), 'client_groups', ['token'], unique=True)

    op.execute("CREATE TYPE submission_status_enum AS ENUM ('pending_upload', 'uploaded', 'processing', 'review_required', 'confirmed', 'failed')")

    op.create_table('passport_submissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('group_id', sa.UUID(), nullable=False),
        sa.Column('agency_id', sa.UUID(), nullable=False),
        sa.Column('client_name', sa.String(length=255), nullable=False),
        sa.Column('client_email', sa.String(length=255), nullable=True),
        sa.Column('image_s3_key', sa.String(length=512), nullable=False),
        sa.Column('thumbnail_s3_key', sa.String(length=512), nullable=True),
        sa.Column('status', postgresql.ENUM('pending_upload', 'uploaded', 'processing', 'review_required', 'confirmed', 'failed', name='submission_status_enum', create_type=False), nullable=False),
        sa.Column('extracted_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('confirmed_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('overall_confidence', sa.Float(), nullable=True),
        sa.Column('mrz_raw', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['group_id'], ['client_groups.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_passport_submissions_agency_id'), 'passport_submissions', ['agency_id'], unique=False)
    op.create_index(op.f('ix_passport_submissions_group_id'), 'passport_submissions', ['group_id'], unique=False)
    op.create_index(op.f('ix_passport_submissions_status'), 'passport_submissions', ['status'], unique=False)

def downgrade() -> None:
    op.drop_table('passport_submissions')
    op.drop_table('client_groups')
    op.execute("DROP TYPE IF EXISTS group_status_enum")
    op.execute("DROP TYPE IF EXISTS submission_status_enum")
