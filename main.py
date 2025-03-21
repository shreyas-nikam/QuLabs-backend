from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import time
import threading
import subprocess
from typing import Dict
from mongo_client import AtlasClient
from bson import ObjectId

# -- SETUP FASTAPI --
app = FastAPI()

# -- SETUP MONGO CONNECTION --
# Adjust the connection string, DB name, and collection name as appropriate.
mongoclient = AtlasClient()

# In-memory container state:
# container_states = {
#    "app_name": {
#       "running_status": "running"|"starting"|"stopped",
#       "last_activity": float (epoch time),
#       "port": int,
#       "docker_image": str,
#       "container_name": str
#    },
#    ...
# }
container_states: Dict[str, Dict] = {}

IDLE_TIMEOUT_SECONDS = 24 * 3600  # 24 hours

def init_idle_checker():
    """Start a background thread that periodically checks for idle containers."""
    def idle_checker():
        while True:
            time.sleep(3600)  # check once per hour
            now = time.time()
            for app_name, state in list(container_states.items()):
                if state["running_status"] == "running":
                    last_active = state["last_activity"]
                    if (now - last_active) > IDLE_TIMEOUT_SECONDS:
                        # Stop container
                        container_name = state["container_name"]
                        subprocess.run(["docker", "stop", container_name], capture_output=True)
                        subprocess.run(["docker", "rm", container_name], capture_output=True)
                        # Mark as stopped
                        state["running_status"] = "stopped"
    threading.Thread(target=idle_checker, daemon=True).start()

init_idle_checker()

def is_container_running(container_name: str) -> bool:
    """Check via `docker ps` if a container is running."""
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name={container_name}"],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())

def run_container(app_name: str, docker_image: str, port: int):
    """
    Actually run the container (blocking). 
    This is called from a background thread if needed.
    """
    # Mark as starting
    container_states[app_name]["running_status"] = "starting"

    container_name = container_states[app_name]["container_name"]
    # Optional: pull the latest image
    subprocess.run(["docker", "pull", docker_image], capture_output=True)

    # Run container
    subprocess.run([
        "docker", "run", "-d", 
        "--name", container_name, 
        "-p", f"{port}:{port}",
        docker_image
    ], capture_output=True)

    # Mark as running
    container_states[app_name]["running_status"] = "running"

    mongoclient.update("lab_design", {"_id": ObjectId(app_name)}, {"$set": {"running_status": "running"}})


@app.get("/")
def read_root(request: Request):
    return {"message": "Hello World 6"}

@app.get("/health-check")
def health_check(request: Request):
    return {"status": "ok 6"}

@app.post("/register_app")
def register_app(data: dict):
    """
    Endpoint for Airflow (or any other tool) to register a new app.
    data = {
      "lab_id": "some_name",
      "docker_image": "myrepo/some_image:latest",
      "port": 8503,
    }
    Will store in Mongo and spin up the container immediately 
    so it runs for 24 hours initially.
    """
    app_name = data.get("lab_id")
    docker_image = data.get("docker_image")
    port = data.get("port")
    if not app_name or not docker_image or not port:
        raise HTTPException(status_code=400, detail="Missing required fields")

    mongoclient.update("lab_design", {"_id": ObjectId(app_name)}, {"$set": {"running_status": "starting"}})


    # Initialize in container_states as "running" from the start
    container_name = f"{app_name}"
    container_states[app_name] = {
        "running_status": "running",
        "last_activity": time.time(),
        "port": port,
        "docker_image": docker_image,
        "container_name": container_name
    }

    # Stop & remove if leftover container with same name
    subprocess.run(["docker", "stop", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)

    # Run the container now
    run_container(app_name, docker_image, port)

    return {"message": f"App {app_name} registered and started successfully."}

@app.delete("/apps/{app_name}")
def remove_app(app_name: str):
    """Delete the app from Mongo and stop/remove any running container."""
    
    if app_name in container_states:
        state = container_states[app_name]
        container_name = state["container_name"]
        subprocess.run(["docker", "stop", container_name], capture_output=True)
        subprocess.run(["docker", "rm", container_name], capture_output=True)
        del container_states[app_name]

    return {"message": f"App {app_name} deleted successfully."}

@app.get("/app/{app_name}", response_class=HTMLResponse)
def serve_app_page(app_name: str, request: Request):
    """
    Main entrypoint for users to open a Streamlit app.
    Checks if the container is running; if not, starts or shows 'starting up' page.
    """
    doc = mongoclient.find("lab_design", {"_id": ObjectId(app_name)})
    if not doc:
        raise HTTPException(status_code=404, detail="App not found in DB")

    # If not in container_states, init it
    if app_name not in container_states:
        container_name = f"{app_name}"
        container_states[app_name] = {
            "running_status": "running" if doc.get("initially_running") else "stopped",
            "last_activity": time.time(),
            "port": doc["port"],
            "docker_image": doc["docker_image"],
            "container_name": container_name
        }

    state = container_states[app_name]
    state["last_activity"] = time.time()

    # Check actual Docker status if state is running
    if state["running_status"] == "running":
        if not is_container_running(state["container_name"]):
            # Mark as stopped if it's not actually running
            state["running_status"] = "stopped"
            mongoclient.update("lab_design", {"_id": ObjectId(app_name)}, {"$set": {"running_status": "stopped"}})

    # If truly running, redirect
    if state["running_status"] == "running":
        return RedirectResponse(url=f"http://{request.client.host}:{state['port']}/{app_name}")
    elif state["running_status"] == "starting":
        # Show "loading" page
        return loading_page(app_name)
    else:
        # state == "stopped"
        # Spin up again
        thread = threading.Thread(
            target=run_container,
            args=(app_name, state["docker_image"], state["port"])
        )
        thread.start()
        return loading_page(app_name)

# TODO: Make the loading page better
def loading_page(app_name: str) -> HTMLResponse:
    """
    Returns an HTML page that auto-polls /status/{app_name} 
    to detect 'running' and then redirect automatically.
    """
    return HTMLResponse(content=f"""
    <html>
        <head>
            <title>Starting {app_name}...</title>
        </head>
        <body>
            <h1>Starting your {app_name} Streamlit app. Please wait...</h1>
            <p>This page will auto-refresh when ready.</p>
            <script>
                async function checkStatus() {{
                    try {{
                        const resp = await fetch('/status/{app_name}');
                        const data = await resp.json();
                        if (data.status === 'running') {{
                            window.location.href = data.url;
                        }}
                    }} catch(e) {{
                        console.error(e);
                    }}
                }}
                setInterval(checkStatus, 3000);
            </script>
        </body>
    </html>
    """, status_code=200)

@app.get("/status/{app_name}")
def status_endpoint(app_name: str, request: Request):
    """Poll this endpoint from the 'loading' page to see if container is running yet."""
    if app_name not in container_states:
        raise HTTPException(status_code=404, detail="App not found in memory.")
    state = container_states[app_name]
    state["last_activity"] = time.time()

    if state["running_status"] == "starting" and is_container_running(state["container_name"]):
        state["running_status"] = "running"
    if state["running_status"] == "running" and not is_container_running(state["container_name"]):
        state["running_status"] = "stopped"

    url = f"http://{request.client.host}:{state['port']}/{app_name}"
    return {"running_status": state["running_status"], "url": url}

