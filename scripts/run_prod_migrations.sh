#!/bin/bash

# Save original state
ORIGINAL_IS_PRODUCTION=$IS_PRODUCTION

# Source .env file if it exists
if [ -f .env ]; then
    source .env
fi

# Set production mode
export IS_PRODUCTION=true

# Run migrations
echo "Running migrations in PRODUCTION mode..."
alembic upgrade head

# Restore original state
if [ -z "$ORIGINAL_IS_PRODUCTION" ]; then
    unset IS_PRODUCTION
else
    export IS_PRODUCTION=$ORIGINAL_IS_PRODUCTION
fi

echo "Migration complete"
