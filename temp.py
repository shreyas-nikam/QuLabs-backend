import requests


endpoint = "https://qucreate.qusandbox.com/qulabs/register_lab"
payload = {
    "lab_id": "67c74c43706b59b673a8d664",
    "docker_image": "qunikamshreyas/67c74c43706b59b673a8d664:latest",
    "port": 8525,
}

response = requests.post(endpoint, json=payload)

if response.status_code == 200:
    print("Lab registered successfully!")
    print("Response:", response.json())

else:
    print("Failed to register lab.")
    print("Status Code:", response.status_code)
    print("Response:", response.text)

