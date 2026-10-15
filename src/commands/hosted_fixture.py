"""Exact existing staging identity; never an alternative credential capability."""
from src.storage import postgres_projection as p


def allowed(authority, *, purpose="runtime"):
    if authority.environment == "local":
        return True
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.storage.hosted_staging import HostedStagingConfig
    repository = getattr(authority, "projections", None)
    config = getattr(repository, "_hosted_config", None)
    if (type(authority) is not PostgresCommandAuthority
            or type(repository) is not p.PostgresProjectionRepository
            or type(config) is not HostedStagingConfig
            or authority.environment != "preview" or repository.environment != "preview"):
        return False
    value = config.parameters()  # Existing immutable file/identity/CA checks, no dial.
    return (value["purpose"] == purpose and value["role"] == repository.user
            and value["database"] == repository.database)


def profile(connection, environment):
    """Additional preview gate on the caller's already validated transaction."""
    if environment == "local":
        return
    p._require(environment == "preview", "staging_workflow_environment_refused")
    from src.commands.postgres_delivery import validate
    validate(connection, environment)
