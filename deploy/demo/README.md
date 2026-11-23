# CiteSure public demo container

One container with the whole app (Postgres + pgvector, API, worker, nginx on port 7860), fake models and the fictional Acme Robotics handbook. Deploy guide (Render, Koyeb, Hugging Face, any VM): [docs/public-demo.md](../../docs/public-demo.md).

| File | Role |
|---|---|
| `Dockerfile` | clones CiteSure from GitHub, builds the frontend, installs the backend, and creates and seeds the database at build time |
| `start.sh` | opens the port with `starting.html` at once, starts Postgres and the API, switches nginx to the app when the API answers, then starts the worker |
| `nginx.conf`, `booting.conf`, `live.conf` | nginx as a normal user; the "starting" locations, then the app's locations |
| `starting.html` | the self-refreshing "CiteSure is waking up" page |

**Sign in** (password for all three: `citesure-demo`):

| User | Try |
|---|---|
| `employee@acme.example` | "How many weeks of paid parental leave do primary caregivers get?" then "What is the maximum severance in weeks?" (refused: HR only) |
| `hr@acme.example` | "How is severance pay calculated?" (answered from the confidential document) |
| `admin@acme.example` | Documents, Workspace, Quality (run the evaluation), Dashboard, Audit log |

Answers come from deterministic fake models, so they are short quotes rather than fluent prose; the citation checks, access control and refusals are the real code. Everything resets when the container restarts.
