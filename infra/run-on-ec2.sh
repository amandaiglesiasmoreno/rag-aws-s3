#!/bin/bash
# Run on the EC2 instance inside the project folder (after creating .env).
set -euo pipefail
sudo docker build -t rag-streamlit .
sudo docker rm -f rag-streamlit 2>/dev/null || true
sudo docker run -d --name rag-streamlit --restart unless-stopped --env-file .env -p 80:8501 rag-streamlit
echo "Streamlit is running on port 80 of this instance."
