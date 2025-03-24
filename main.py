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

load_dotenv()

app = FastAPI()
mongoclient = AtlasClient()
container_states: Dict[str, Dict] = {}

# TODO: Change this to 24 hours
IDLE_TIMEOUT_SECONDS = 600  # 24 hours

def init_idle_checker():
    """Start a background thread that periodically checks for idle containers."""
    def idle_checker():
        global container_states
        logging.info("Idle checker started.")
        while True:
            time.sleep(60)  # TODO: Change this to one hour
            now = time.time()
            for lab_id, state in list(container_states.items()):
                if state["running_status"] == "running":
                    last_active = state["last_activity"]
                    if (now - last_active) > IDLE_TIMEOUT_SECONDS:
                        # Stop container
                        container_name = state["container_name"]
                        subprocess.run(["docker", "stop", container_name], capture_output=True)
                        subprocess.run(["docker", "rm", container_name], capture_output=True)
                        # Mark as stopped
                        state["running_status"] = "stopped"
                        logging.info(f"Marked lab {lab_id} as 'stopped' due to inactivity.")
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

def run_container(lab_id: str, docker_image: str, port: int):
    """
    Actually run the container (blocking). 
    This is called from a background thread if needed.
    """
    global container_states
    logging.info(f"run_container() called with lab_id: {lab_id}, docker_image: {docker_image}, port: {port}")

    # Mark as starting
    logging.info(f"Marking lab {lab_id} status as 'starting'")
    container_states[lab_id]["running_status"] = "starting"

    # Get container name
    container_name = container_states[lab_id]["container_name"]
    logging.info(f"Retrieved container name: {container_name} for lab {lab_id}")

    # Run container and stream output
    logging.info(f"Running docker container for lab {lab_id} with image {docker_image} on port {port}")
    process = subprocess.Popen(
        ["sudo", "docker", "run", "-d", "--name", container_name, "-p", f"{port}:8501", docker_image],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line-buffered
        universal_newlines=True
    )

    # Log streaming output line-by-line
    for line in process.stdout:
        logging.info(f"Docker run output: {line.strip()}")

    process.wait()
    if process.returncode != 0:
        logging.error(f"Error running docker container for lab {lab_id}")
        raise Exception(f"Error running docker container for lab {lab_id}")

    logging.info(f"Docker run command executed for container {container_name}")

    # Mark as running
    logging.info(f"Marking lab {lab_id} status as 'running'")
    container_states[lab_id]["running_status"] = "running"

    logging.info(f"Updating MongoDB status to 'running' for lab {lab_id}")
    mongoclient.update("lab_design", {"_id": ObjectId(lab_id)}, {"$set": {"running_status": "running"}})

    logging.info(f"run_container() completed for lab {lab_id}")


# Configure logging to display INFO level messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_repo(lab_id):
    GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")
    if not GITHUB_USERNAME:
        raise ValueError("GITHUB_USERNAME environment variable is not set.")
    
    logging.info(f"Pulling repo for lab: {lab_id}")
    
    # Ensure the target directory exists (without sudo to maintain proper ownership)
    target_dir = "/home/user1/QuLabs"
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
    
    os.chdir(f"/home/user1/QuLabs/{lab_id}")
    
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

import requests

def wait_for_image(image_tag, max_wait=300, poll_interval=30):
    elapsed = 0
    print(f"Waiting for image: {image_tag}")
    while elapsed < max_wait:
        print("Polling for image after {elapsed} seconds")
        if check_image_exists(image_tag):
            return True
        print("Image not found yet. Sleeping...")
        time.sleep(poll_interval)
        elapsed += poll_interval
    return False

def check_image_exists(image_tag):
    print(f"Checking if image exists: {image_tag}")
    url = f"https://hub.docker.com/v2/repositories/{image_tag.replace(':', '/tags/')}"
    print(f"Checking if image exists: {url}")
    response = requests.get(url)
    print(f"Checking if image exists: {response.status_code}")
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
    global container_states
    lab_id = data.get("lab_id")
    docker_image = data.get("docker_image")
    port = data.get("port")
    print(data)
    if not lab_id or not docker_image or not port:
        raise HTTPException(status_code=400, detail="Missing required fields")
    print(f"Registering lab: {lab_id}")
    mongoclient.update("lab_design", {"_id": ObjectId(lab_id)}, {"$set": {"running_status": "running"}})
    print(f"Checking if image exists: {docker_image}")

    if wait_for_image(docker_image):
        print(f"Image {docker_image} exists.")
    else:
        raise HTTPException(status_code=400, detail="Docker image not found")

    # Initialize in container_states as "running" from the start
    container_name = f"{lab_id}"
    container_states[lab_id] = {
        "running_status": "running",
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
    print(f"Pulling repo for lab: {lab_id}")
    get_repo(lab_id)
    print(f"Running codelab for lab: {lab_id}")
    run_codelab(lab_id)
    print(f"Updating nginx snippet for lab: {lab_id}")
    add_lab_sh_command(lab_id, port)
    print(f"Lab {lab_id} registered and started successfully.")

    return {"message": f"Lab {lab_id} registered and started successfully."}

@app.delete("/labs/{lab_id}")
def remove_app(lab_id: str):
    """Delete the lab from Mongo and stop/remove any running container."""
    global container_states
    if lab_id in container_states:
        state = container_states[lab_id]
        container_name = state["container_name"]
        subprocess.run(["sudo", "docker", "stop", container_name], capture_output=True)
        subprocess.run(["sudo", "docker", "rm", container_name], capture_output=True)
        del container_states[lab_id]

    return {"message": f"Lab {lab_id} deleted successfully."}

@app.get("/lab/{lab_id}", response_class=HTMLResponse)
def serve_lab_page(lab_id: str, request: Request):
    """
    Main entrypoint for users to open a Streamlit lab.
    Checks if the container is running; if not, starts or shows 'starting up' page.
    """
    global container_states
    doc = mongoclient.find("lab_design", {"_id": ObjectId(lab_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lab not found in DB")
    doc = doc[0]
    
    print(container_states)

    # If not in container_states, init it
    if lab_id not in container_states:
        container_name = f"{lab_id}"
        container_states[lab_id] = {
            "running_status": "running" if doc.get("running_status") else "stopped",
            "last_activity": time.time(),
            "port": doc["port"],
            "docker_image": doc["docker_image"],
            "container_name": container_name
        }
    port = container_states[lab_id]["port"]
    state = container_states[lab_id]
    state["last_activity"] = time.time()

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

def loading_page(lab_id: str, request: Request) -> HTMLResponse:
    """
    Returns an HTML page that auto-polls /status/{lab_id} 
    to detect 'running' and then redirect automatically.
    """
    return HTMLResponse(content=f"""
    <html>
      <head>
        <title>Starting {lab_id}...</title>
        <style>
          body {{
            background: linear-gradient(135deg, #f6d365 0%, #fda085 100%);
            color: #333;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            text-align: center;
            margin: 0;
            padding: 0;
            height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
          }}
          h1 {{
            font-size: 2.5em;
            margin-bottom: 0.2em;
          }}
          p {{
            font-size: 1.2em;
          }}
          .spinner {{
            margin: 40px auto;
            width: 50px;
            height: 50px;
            border: 5px solid rgba(255, 255, 255, 0.6);
            border-top: 5px solid #fff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
          }}
          @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
          }}
          .loading-text {{
            font-size: 1.1em;
            animation: fadeInOut 2s infinite;
          }}
          @keyframes fadeInOut {{
            0% {{ opacity: 0.2; }}
            50% {{ opacity: 1; }}
            100% {{ opacity: 0.2; }}
          }}
        </style>
      </head>
      <body>
        <h1>Starting your "{lab_id}" Streamlit app...</h1>
        <div class="spinner"></div>
        <p class="loading-text">Please wait, loading in progress...</p>
        <script>
          async function checkStatus() {{
            try {{
              const resp = await fetch('/status/{lab_id}');
              const data = await resp.json();
              if (data.status === 'running') {{
                window.location.href = data.url;
              }}
            }} catch(e) {{
              console.error(e);
            }}
          }}
          setInterval(checkStatus, 10000);
        </script>
      </body>
    </html>
    """, status_code=200)


@app.get("/status/{lab_id}")
def status_endpoint(lab_id: str, request: Request):
    """Poll this endpoint from the 'loading' page to see if container is running yet."""
    global container_states
    if lab_id not in container_states:
        raise HTTPException(status_code=404, detail="Lab not found in memory.")
    state = container_states[lab_id]
    state["last_activity"] = time.time()
    
    logging.info(container_states)

    if state["running_status"] == "starting" and is_container_running(state["container_name"]):
        state["running_status"] = "running"
    if state["running_status"] == "running" and not is_container_running(state["container_name"]):
        state["running_status"] = "stopped"

    url = f"http://{request.client.host}:{state['port']}/{lab_id}"
    return {"running_status": state["running_status"], "url": url}

