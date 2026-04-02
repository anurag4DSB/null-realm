# null-realm

## Architecture Overview

Null Realm is a multi-agent learning lab built on Kubernetes, designed as a platform for experimenting with AI agent workflows and collaboration patterns. The system provides a complete infrastructure for developing, deploying, and observing autonomous agents that can perform complex tasks through coordinated multi-step workflows.

The platform follows a microservices architecture with three main components: an API service that provides REST endpoints and WebSocket connections, worker processes that execute agent tasks using LangGraph, and a chat UI built with Chainlit. The system leverages Argo Workflows for orchestration, NATS JetStream for event streaming, and maintains a comprehensive registry of tools, prompts, assistants, and workflows. Infrastructure is managed through Pulumi for GCP resources and Kubernetes manifests for local development with Kind.

The codebase emphasizes observability with OpenTelemetry tracing, code context indexing using AST parsing and embeddings stored in pgvector, and relationship mapping through Neo4j. This allows agents to understand and navigate codebases while providing operators with deep insights into system behavior and agent decision-making processes.

## Service Map

- **API Service** (`nullrealm/api/`) → communicates with Registry database, NATS bus, and Argo Workflows orchestrator
- **Worker Service** (`nullrealm/worker/`) → executes agent tasks, reads from Registry, publishes events to NATS
- **Chat UI** (`ui/app.py`) → connects to API via WebSocket for real-time agent interactions
- **Registry** (`nullrealm/registry/`) → central data store accessed by API and Worker services
- **Context System** (`nullrealm/context/`) → indexes codebases and stores embeddings/relationships for agent context
- **Orchestrator** (`nullrealm/orchestrator/`) → manages workflow execution through Argo Workflows
- **Communication** (`nullrealm/communication/`) → handles event streaming between services via NATS JetStream
- **Infrastructure** (`infra/`) → provisions GCP resources (GKE, Cloud SQL, networking) and manages K8s deployments

## Key Abstractions

- **BaseTool**: Interface for agent tools with async execution capability
- **AgentState**: LangGraph state management for ReAct agent workflows  
- **StreamEvent**: Event models for real-time agent-to-UI communication
- **Registry Models**: SQLAlchemy ORM models (Tool, Prompt, Assistant, Workflow) with corresponding Pydantic schemas
- **WorkflowExecutor**: Orchestrates multi-step agent workflows via Argo
- **CodeChunk/CodeRelationship**: AST-based code representation for context indexing
- **PgVectorStore/Neo4jStore**: Dual storage backend for embeddings and graph relationships
- **NATSBus**: Messaging abstraction for pub/sub communication
- **Settings**: Centralized configuration via Pydantic with environment variable loading

## API Surface

### HTTP Endpoints
- `GET /health` - Health check
- `GET /status` - Service status  
- `GET|POST|PUT|DELETE /tools/*` - Tool CRUD operations
- `GET|POST|PUT|DELETE /prompts/*` - Prompt management
- `GET|POST|PUT|DELETE /assistants/*` - Assistant configuration
- `GET|POST|PUT|DELETE /workflows/*` - Workflow definitions
- `POST /workflows/{workflow_id}/execute` - Execute workflow

### WebSocket Routes  
- `WS /ws/{session_id}` - Real-time chat with agent streaming

### CLI Commands (via invoke)
- `invoke dev` - Full local development cycle
- `invoke kind-up|kind-down` - Kind cluster management
- `invoke build|load-images|deploy-local` - Local deployment
- `invoke pulumi-up|pulumi-destroy` - GCP infrastructure
- `invoke sql-start|sql-stop|gcp-status` - Cloud resource management

## File Tree (annotated)

```
null-realm/
├── .env.example                     # Environment template
├── Dockerfile.{api,ui,worker}       # Multi-service containerization  
├── docker-compose.yaml              # Local development stack
├── pyproject.toml                   # Python dependencies via uv
├── tasks.py                         # Invoke CLI for dev workflows
├── agent_configs/                   # YAML/Markdown configuration
│   ├── assistants/                  # Agent personality definitions
│   ├── prompts/                     # Agent instruction templates
│   ├── tools/                       # Available tool configurations
│   └── workflows/                   # Multi-step workflow definitions
├── docs/architecture/               # Architecture decisions and open questions
├── infra/                          # Infrastructure as code
│   ├── k8s/                        # Kubernetes manifests (Kind + GKE)
│   ├── prometheus/                 # Observability configuration
│   └── pulumi/                     # GCP resource provisioning
├── nullrealm/                      # Main application package
│   ├── api/                        # FastAPI routes and WebSocket handlers
│   ├── communication/              # NATS event streaming
│   ├── context/                    # Code indexing and embedding system
│   ├── observability/              # OpenTelemetry tracing setup
│   ├── orchestrator/               # Argo Workflows integration
│   ├── registry/                   # SQLAlchemy models and database
│   ├── tools/                      # Agent tool implementations
│   └── worker/                     # LangGraph agent execution
├── scripts/kind-config.yaml        # Kind cluster configuration
└── ui/app.py                       # Chainlit chat interface
```

## Key Files

**`nullrealm/main.py`** - FastAPI application entry point that orchestrates service startup, initializes database connections, NATS messaging, and OpenTelemetry tracing. Defines the complete API surface with CORS middleware and lifespan management.

**`nullrealm/worker/langgraph_agent.py`** - Core LangGraph ReAct agent implementation with streaming support. Defines the agent state, tool execution flow, and provides both blocking and async streaming interfaces for agent task execution.

**`nullrealm/context/indexer.py`** - AST-based Python code analysis system that parses repositories, extracts function signatures and relationships, and prepares code chunks for embedding generation and graph storage.

**`tasks.py`** - Comprehensive invoke CLI providing the complete development workflow from local Kind cluster creation through GCP infrastructure provisioning, with specific commands for cost management and deployment automation.

**`nullrealm/registry/seed.py`** - Database seeding system that loads agent configurations from YAML/Markdown files in `agent_configs/` into the SQLAlchemy registry, enabling dynamic agent assembly and workflow execution.