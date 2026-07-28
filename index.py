"""
index.py

nanoMon Flask web server.

Purpose:
    Serves the dashboard page and provides Docker statistics
    through an AJAX JSON endpoint.

This module:
    - serves dashboard.html
    - provides /api/docker-stats

This module does not:
    - collect Docker statistics directly
    - format HTML
    - manage containers
"""

from flask import Flask, render_template, jsonify
from statistics import DockerStatistics
from display import DockerDisplay

app = Flask(__name__)


@app.route("/")
def dashboard():
    """
    Display the main nanoMon dashboard page.

    Returns:
        Rendered HTML dashboard.
    """

    return render_template(
        "dashboard.html"
    )


@app.route("/api/docker-stats")
def docker_stats():
    """
    Provide Docker statistics as JSON.

    Returns:
        JSON formatted Docker statistics.
    """

    docker_statistics = DockerStatistics()

    raw_data = docker_statistics.collect_all()

    display = DockerDisplay(
        raw_data
    )

    formatted_data = display.prepare()

    return jsonify(
        formatted_data
    )


if __name__ == "__main__":
    """
    Start Flask development server.

    Access:
        http://127.0.0.1:5000
    """

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )