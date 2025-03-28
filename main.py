import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import time
import threading
import subprocess
from typing import Dict
from mongo_client import AtlasClient
from bson import ObjectId
import os
from dotenv import load_dotenv
import logging
from jinja2 import Environment, FileSystemLoader
import json
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

load_dotenv()
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
env = Environment(loader=FileSystemLoader(templates_dir))
app = FastAPI()
mongoclient = AtlasClient()
container_states: Dict[str, Dict] = {}


def save_container_states(file_path="container_states.json"):
    try:
        with open(file_path, "w") as f:
            json.dump(container_states, f)
        logging.info("Container states saved successfully.")
    except Exception as e:
        logging.error(f"Error saving container states: {e}")

def load_container_states(file_path="container_states.json"):
    global container_states
    try:
        with open(file_path, "r") as f:
            container_states = json.load(f)
        logging.info("Container states loaded successfully.")
    except FileNotFoundError:
        logging.info("No previous container states file found. Starting fresh.")
        container_states = {}
    except Exception as e:
        logging.error(f"Error loading container states: {e}")
        container_states = {}


# TODO: Change this to 24 hours
IDLE_TIMEOUT_SECONDS = 86400  # 24 hours

def init_idle_checker():
    """Start a background thread that periodically checks for idle containers."""
    if not container_states:
        load_container_states()
    logging.info("Initializing idle checker.")
    logging.info(f"Initial container states: {container_states}")
    def idle_checker():
        
        logging.info("Idle checker started.")
        logging.info(f"Initial container states: {container_states}")
        while True:
            time.sleep(3600)  # TODO: Change this to one hour
            now = time.time()
            for lab_id, state in list(container_states.items()):
                if state["running_status"] == "running":
                    last_active = state["last_activity"]
                    if (now - last_active) > IDLE_TIMEOUT_SECONDS:
                        # Stop container
                        container_name = state["container_name"]
                        logging.info(f"Stopping container {container_name} due to inactivity.")
                        subprocess.run(["sudo", "docker", "stop", container_name], capture_output=True)
                        subprocess.run(["sudo", "docker", "rm", container_name], capture_output=True)
                        subprocess.run(["sudo", "docker", "system", "prune", "-a"], capture_output=True)
                        # Mark as stopped
                        state["running_status"] = "stopped"
                        logging.info(f"Marked lab {lab_id} as 'stopped' due to inactivity.")
                        save_container_states()
    threading.Thread(target=idle_checker, daemon=True).start()

init_idle_checker()

def is_container_running(container_name: str) -> bool:
    """Check via `docker ps` if a container is running."""
    result = subprocess.run(
        ["sudo", "docker", "ps", "-q", "-f", f"name={container_name}"],
        capture_output=True, text=True
    )
    logging.info(f"Checking if container {container_name} is running: {bool(result.stdout.strip())}")
    return bool(result.stdout.strip())

def container_exists(container_name: str) -> bool:
    """Return True if a container with the exact name exists (running or not)."""
    cmd = [
        "sudo", "docker", "ps", "-a", 
        "--filter", f"name=^{container_name}$", 
        "--format", "{{.Names}}"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    exists = bool(result.stdout.strip())
    logging.info(f"Container '{container_name}' exists: {exists}")
    return exists

def container_running(container_name: str) -> bool:
    """Return True if a container with the exact name is running."""
    cmd = [
        "sudo", "docker", "ps", 
        "--filter", f"name=^{container_name}$", 
        "--format", "{{.Names}}"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    running = bool(result.stdout.strip())
    logging.info(f"Container '{container_name}' running: {running}")
    return running

def start_existing_container(container_name: str, lab_id: str):
    """Start a container that exists but is not running."""
    logging.info(f"Container {container_name} exists but is not running. Starting it.")
    cmd = ["sudo", "docker", "start", container_name]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    for line in process.stdout:
        logging.info(f"Docker start output: {line.strip()}")
    process.wait()
    if process.returncode != 0:
        logging.error(f"Error starting container {container_name} for lab {lab_id}")
        raise Exception(f"Error starting container {container_name} for lab {lab_id}")
    logging.info(f"Container {container_name} started successfully.")

def run_new_container(container_name: str, docker_image: str, port: int, lab_id: str):
    """Run a new container using docker run."""
    logging.info(f"Running new docker container for lab {lab_id} with image {docker_image} on port {port}")
    process = subprocess.Popen(
        ["sudo", "docker", "run", "-d", "--name", container_name, "-p", f"{port}:8501", docker_image],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    for line in process.stdout:
        logging.info(f"Docker run output: {line.strip()}")
    process.wait()
    if process.returncode != 0:
        logging.error(f"Error running docker container for lab {lab_id}")
        raise Exception(f"Error running docker container for lab {lab_id}")
    logging.info(f"Docker run command executed successfully for container {container_name}")

def update_container_state_and_db(lab_id: str):
    """Mark the container as running, save state and update the database."""
    container_states[lab_id]["running_status"] = "running"
    save_container_states()
    logging.info(f"Updating MongoDB status to 'running' for lab {lab_id}")
    mongoclient.update("lab_design", {"_id": ObjectId(lab_id)}, {"$set": {"running_status": "running"}})
    logging.info(f"Container state updated for lab {lab_id}")

def run_container(lab_id: str, docker_image: str, port: int):
    """
    Actually run the container (blocking). 
    This is called from a background thread if needed.
    """
    # Update container_states for this lab
    if lab_id not in container_states:
        container_states[lab_id] = {
            "running_status": "starting",
            "last_activity": time.time(),
            "port": port,
            "docker_image": docker_image,
            "container_name": lab_id
        }
    else:
        container_states[lab_id].update({
            "running_status": "starting",
            "last_activity": time.time(),
            "port": port,
            "docker_image": docker_image,
            "container_name": lab_id
        })

    logging.info(f"run_container() called with lab_id: {lab_id}, docker_image: {docker_image}, port: {port}")
    container_name = container_states[lab_id]["container_name"]
    logging.info(f"Retrieved container name: {container_name} for lab {lab_id}")

    if container_exists(container_name):
        if container_running(container_name):
            logging.info(f"Container {container_name} is already running.")
        else:
            start_existing_container(container_name, lab_id)
        # Update state and DB, then return
        update_container_state_and_db(lab_id)
        logging.info(f"run_container() completed for lab {lab_id}")
        return

    # If container does not exist, run a new one
    run_new_container(container_name, docker_image, port, lab_id)
    update_container_state_and_db(lab_id)
    logging.info(f"run_container() completed for lab {lab_id}")


def get_repo(lab_id):
    GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")
    if not GITHUB_USERNAME:
        raise ValueError("GITHUB_USERNAME environment variable is not set.")
    
    logging.info(f"Pulling repo for lab: {lab_id}")
    
    # Ensure the target directory exists (without sudo to maintain proper ownership)
    target_dir = "/home/ubuntu/QuLabs"
    os.makedirs(target_dir, exist_ok=True)
    os.chdir(target_dir)
    
    if not os.path.isdir(lab_id):
        command = f"git clone https://github.com/{GITHUB_USERNAME}/{lab_id}.git"
        logging.info(f"Running command: {command}")
        subprocess.run(command, shell=True, check=True)
        logging.info("Git clone completed successfully.")
    else:
        os.chdir(lab_id)
        command = "git pull origin main"
        logging.info(f"Running command: {command}")
        subprocess.run(command, shell=True, check=True)
        logging.info("Git pull completed successfully.")

def run_codelab(lab_id):
    # Build directory names using Python string formatting
    lab_doc = f"{lab_id}_documentation"
    lab_user_guide = f"{lab_id}_user_guide"
    
    os.chdir(f"/home/ubuntu/QuLabs/{lab_id}")
    
    # Export documentation.md
    if not os.path.isdir(lab_doc):
        command = "claat export documentation.md"
        logging.info(f"Running command: {command}")
        subprocess.run(command, shell=True, check=True)
        logging.info("Documentation export completed successfully.")
    else:
        command = f"rm -rf {lab_doc} && claat export documentation.md"
        logging.info(f"Running command: {command}")
        subprocess.run(command, shell=True, check=True)
        logging.info("Documentation re-export completed successfully.")
        
    # Export user_guide.md
    if not os.path.isdir(lab_user_guide):
        command = "claat export user_guide.md"
        logging.info(f"Running command: {command}")
        subprocess.run(command, shell=True, check=True)
        logging.info("User guide export completed successfully.")
    else:
        command = f"rm -rf {lab_user_guide} && claat export user_guide.md"
        logging.info(f"Running command: {command}")
        subprocess.run(command, shell=True, check=True)
        logging.info("User guide re-export completed successfully.")
    
    # Create directories for documentation and user guide using sudo
    command = f"sudo mkdir -p /var/www/codelabs/{lab_id}/documentation"
    logging.info(f"Running command: {command}")
    subprocess.run(command, shell=True, check=True)
    logging.info("Created directory for documentation.")
    
    command = f"sudo mkdir -p /var/www/codelabs/{lab_id}/user_guide"
    logging.info(f"Running command: {command}")
    subprocess.run(command, shell=True, check=True)
    logging.info("Created directory for user guide.")
    
    # Copy files to the destination directories
    command = f"sudo cp -r {lab_doc}/. /var/www/codelabs/{lab_id}/documentation/"
    logging.info(f"Running command: {command}")
    subprocess.run(command, shell=True, check=True)
    logging.info("Copied documentation files.")
    
    command = f"sudo cp -r {lab_user_guide}/. /var/www/codelabs/{lab_id}/user_guide/"
    logging.info(f"Running command: {command}")
    subprocess.run(command, shell=True, check=True)
    logging.info("Copied user guide files.")

def add_lab_sh_command(lab_id, port):
    command = f"/usr/local/bin/add_lab.sh {lab_id} {port}"
    logging.info(f"Running command: {command}")
    subprocess.run(command, shell=True, check=True)
    logging.info("add_lab.sh command executed successfully.")


@app.get("/")
def read_root(request: Request):
    return {"message": "Hello World"}

@app.get("/health-check")
def health_check(request: Request):
    return {"status": "ok"}


def wait_for_image(image_tag, max_wait=300, poll_interval=30):
    elapsed = 0
    logging.info(f"Waiting for image: {image_tag}")
    while elapsed < max_wait:
        logging.info(f"Polling for image after {elapsed} seconds")
        if check_image_exists(image_tag):
            return True
        logging.info("Image not found yet. Sleeping...")
        time.sleep(poll_interval)
        elapsed += poll_interval
    return False

def check_image_exists(image_tag):
    logging.info(f"Checking if image exists: {image_tag}")
    url = f"https://hub.docker.com/v2/repositories/{image_tag.replace(':', '/tags/')}"
    logging.info(f"Checking if image exists: {url}")
    response = requests.get(url)
    logging.info(f"Checking if image exists: {response.status_code}")
    return response.status_code == 200

@app.post("/register_lab")
def register_lab(data: dict):
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
    
    lab_id = data.get("lab_id")
    docker_image = data.get("docker_image")
    port = data.get("port")
    logging.info(data)
    if not lab_id or not docker_image or not port:
        raise HTTPException(status_code=400, detail="Missing required fields")
    logging.info(f"Registering lab: {lab_id}")
    logging.info(f"Checking if image exists: {docker_image}")

    if wait_for_image(docker_image):
        logging.info(f"Image {docker_image} exists.")
    else:
        raise HTTPException(status_code=400, detail="Docker image not found")

    # Initialize in container_states as "running" from the start
    container_name = f"{lab_id}"
    container_states[lab_id] = {
        "running_status": "starting",
        "last_activity": time.time(),
        "port": port,
        "docker_image": docker_image,
        "container_name": container_name
    }
    
    logging.info(f"Registering lab {lab_id} with Docker image {docker_image} on port {port}")
    logging.info(container_states)

    # Stop & remove if leftover container with same name
    subprocess.run(["sudo", "docker", "stop", container_name], capture_output=True)
    subprocess.run(["sudo", "docker", "rm", container_name], capture_output=True)

    # Run the container now
    run_container(lab_id, docker_image, port)

    # pull the repo, run the codelab and update the nginx snippet
    logging.info(f"Pulling repo for lab: {lab_id}")
    get_repo(lab_id)
    logging.info(f"Running codelab for lab: {lab_id}")
    run_codelab(lab_id)
    logging.info(f"Updating nginx snippet for lab: {lab_id}")
    add_lab_sh_command(lab_id, port)
    logging.info(f"Lab {lab_id} registered and started successfully.")
    container_states[lab_id]["running_status"] = "running"
    
    save_container_states()

    return {"message": f"Lab {lab_id} registered and started successfully."}

@app.delete("/labs/{lab_id}")
def remove_app(lab_id: str):
    """Delete the lab from Mongo and stop/remove any running container."""
    
    if lab_id in container_states:
        state = container_states[lab_id]
        container_name = state["container_name"]
        subprocess.run(["sudo", "docker", "stop", container_name], capture_output=True)
        subprocess.run(["sudo", "docker", "rm", container_name], capture_output=True)
        del container_states[lab_id]
        save_container_states()
        logging.info(f"Lab {lab_id} deleted successfully.")

    return {"message": f"Lab {lab_id} deleted successfully."}

@app.get("/lab/{lab_id}", response_class=HTMLResponse)
def serve_lab_page(lab_id: str, request: Request):
    """
    Main entrypoint for users to open a Streamlit lab.
    Checks if the container is running; if not, starts or shows 'starting up' page.
    """
    try:
        doc = mongoclient.find("lab_design", {"_id": ObjectId(lab_id)})
    except Exception as e:
        return lab_does_not_exist_page(lab_id, request)
    
    if not doc:
        return lab_does_not_exist_page(lab_id, request)
    doc = doc[0]
    
    logging.info(container_states)

    # If not in container_states, init it
    if lab_id not in container_states:
        container_name = f"{lab_id}"
        container_states[lab_id] = {
            "running_status": doc.get("running_status", "stopped"),
            "last_activity": time.time(),
            "port": doc["port"],
            "docker_image": doc["docker_image"],
            "container_name": container_name
        }
        
    port = container_states[lab_id]["port"]
    state = container_states[lab_id]
    state["last_activity"] = time.time()
    container_states[lab_id] = state
    save_container_states()

    # Check actual Docker status if state is running
    if state["running_status"] == "running":
        if not is_container_running(state["container_name"]):
            # Mark as stopped if it's not actually running
            state["running_status"] = "stopped"
            mongoclient.update("lab_design", {"_id": ObjectId(lab_id)}, {"$set": {"running_status": "stopped"}})

    # If truly running, redirect
    if state["running_status"] == "running":
        return RedirectResponse(url=f"http://{request.client.host}:{port}/{lab_id}")
    elif state["running_status"] == "starting":
        # Show "loading" page
        return loading_page(lab_id, request=request)
    else:
        # state == "stopped"
        # Spin up again
        thread = threading.Thread(
            target=run_container,
            args=(lab_id, state["docker_image"], state["port"])
        )
        thread.start()
        return loading_page(lab_id, request=request)

@app.get("/loading/{lab_id}", response_class=HTMLResponse)
def get_loading_page(lab_id: str, request: Request):
    return loading_page(lab_id, request)


def loading_page(lab_id: str, request: Request) -> HTMLResponse:
    """
    Returns an HTML page that auto-polls /status/{lab_id} 
    to detect 'running' and then redirect automatically.
    """
    logging.info("Lab id in loading page: " + lab_id)
    template = env.get_template("loading_page.html")
    rendered_html = template.render(lab_id=lab_id)
    return HTMLResponse(content=rendered_html, status_code=200)


def lab_does_not_exist_page(lab_id: str, request: Request) -> HTMLResponse:
    template = env.get_template("lab_not_found.html")
    rendered_html = template.render()
    return HTMLResponse(content=rendered_html, status_code=404)
    

@app.get("/status/{lab_id}")
def status_endpoint(lab_id: str, request: Request):
    """Poll this endpoint from the 'loading' page to see if container is running yet."""
    
    if lab_id not in container_states:
        try:
            lab = mongoclient.find("lab_design", {"_id": ObjectId(lab_id)})
        except Exception as e:
            return lab_does_not_exist_page(lab_id, request)
        
        if not lab:
            return lab_does_not_exist_page(lab_id, request)
        lab = lab[0]
        container_name = f"{lab_id}"
        container_states[lab_id] = {
            "running_status": lab.get("running_status", "stopped"),
            "last_activity": time.time(),
            "port": lab["port"],
            "docker_image": lab["docker_image"],
            "container_name": container_name
        }
        container_states["running_status"] = "starting"
        save_container_states()
        run_container(lab_id, lab["docker_image"], lab["port"])
        container_states["running_status"] = "running"
        save_container_states()
        
    state = container_states[lab_id]
    state["last_activity"] = time.time()
    logging.info(container_states)

    if state["running_status"] == "starting" and is_container_running(state["container_name"]):
        state["running_status"] = "running"
    if state["running_status"] == "running" and not is_container_running(state["container_name"]):
        state["running_status"] = "stopped"
        run_container(lab_id, state["docker_image"], state["port"])
        state["running_status"] = "starting"

    url = f"http://{request.client.host}:{state['port']}/{lab_id}"
    save_container_states()
    
    return {"running_status": state["running_status"], "url": url}

