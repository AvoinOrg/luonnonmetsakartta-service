# Luonnonmetsäkartta Service

This repository contains the FastAPI backend service for the [Luonnonmetsäkartat](https://github.com/AvoinOrg/avoin-map/tree/luonnonmetsakartat) applet on [Avoin Map](https://github.com/AvoinOrg/avoin-map). It handles data management for forest areas, layers, and images, and integrates with several external services.

## Core Technologies
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Database**: PostgreSQL with [PostGIS](https://postgis.net/) for spatial data storage.
- **Database Migrations**: [Alembic](https://alembic.sqlalchemy.org/en/latest/)
- **Authentication**: [Zitadel](https://zitadel.com/) for OIDC-based authentication.
- **Map Publishing**: [GeoServer](https://geoserver.org/)
- **File Storage**: S3-compatible object storage.
- **Containerization**: Docker & Docker Compose

---

## Getting Started

The application is designed to be run using Docker Compose, which orchestrates the application container and its database dependencies.

### Prerequisites
- Docker
- Docker Compose

### Configuration

1.  **Create Environment File**: Copy the template file to create your local environment configuration.
    ```bash
    cp .env.template .env
    ```

2.  **Set Compose Profile**: Open the `.env` file and set the `COMPOSE_PROFILES` variable. For most development work, `sandbox` is the recommended profile.
    ```env
    # .env
    COMPOSE_PROFILES=sandbox # dev, sandbox, or prod
    ```

3.  **Configure Sandbox Environment**: The `sandbox` profile connects the service to shared sandbox instances of PostGIS, GeoServer, and S3 storage. This is the most effective way to develop, as it mirrors the production setup.

    **IMPORTANT**: Fill in the environment variables in your `.env` file with the credentials for the **sandbox environment**, not the production ones. This includes `POSTGRES_*`, `GEOSERVER_*`, and `ZITADEL_*` variables.

### Running the Application

Use Docker Compose to build and run the services defined in your selected profile.

```bash
# Build and run the services in the background
docker-compose up --build -d
```

To see logs from the running containers:
```bash
docker-compose logs -f
```

---

## Development Environment

### VS Code & Dev Containers

This project includes a template for a VS Code Dev Container, providing a fully configured and consistent development environment.

1.  **Rename the Template**: In the `.devcontainer` directory, rename `devcontainer.template.json` to `devcontainer.json`.
2.  **Configure Profile**: Open `devcontainer.json` and ensure the `service` and `runServices` properties match your desired profile (e.g., `app-sandbox`).
3.  **Launch**: Open the project folder in VS Code and use the command **"Dev Containers: Reopen in Container"**. This will build the Docker environment and connect your VS Code instance to the running application container.

### Jupyter Notebooks for Exploration

In the `dev` and `sandbox` profiles, a Jupyter Notebook server is also started. This provides a powerful environment for interactive testing, data exploration, and prototyping new features.

-   **Access**: Navigate to `http://localhost:<NOTEBOOK_PORT>` in your browser (e.g., `http://localhost:8888` if using the default port from `.env.template`).
-   **Authentication**: You will be prompted for a token. Use the value of `NOTEBOOK_TOKEN` from your `.env` file.

The `notebooks/` directory is mounted into the container, so you can create and edit notebooks locally, and they will be available in the Jupyter environment.

### Database Migrations

Database schema changes are managed with Alembic. To generate or apply migrations, you need to run commands inside the application container.

1.  **Access the container shell**:
    ```bash
    docker-compose exec app-sandbox bash
    ```

2.  **Run Alembic commands**:
    ```bash
    # Auto-generate a new migration script based on model changes
    poetry run alembic revision --autogenerate -m "Your migration description"

    # Apply the latest migrations to the database
    poetry run alembic upgrade head
    ```

---

## Testing

The project uses a hybrid testing strategy:

-   **Local Tests**: A dedicated test database (`postgis-test`) is included in the `docker-compose.yml` for running local unit and integration tests that do not require external services.
-   **Sandbox Tests**: The most important tests are run against the live sandbox environment. This ensures that the integrations with PostGIS, GeoServer, and other services are working correctly. These tests are typically located in files like `main_prod_test.py` and `geoserver_prod_test.py`.

### A Note on Test Data

Please be aware that running the complete test suite, especially the sandbox tests, requires access to specific test datasets. This data is not included in this public repository and cannot be made public. To gain access to the test