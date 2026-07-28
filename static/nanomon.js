/*
nanoMon dashboard client.
Loads Docker statistics and updates dashboard elements.
*/

function loadStatistics() {
    fetch("/api/docker-stats")
        .then(response => response.json())
        .then(data => {
            updateTimestamp(data.timestamp);
            updateSummary(data.summary_cards);
            updateRunningContainers(data.running_containers);
            updateStoppedContainers(data.stopped_containers);
        })
        .catch(error => {
            console.error("Unable to load Docker statistics:", error);
        });
}

function updateTimestamp(timestamp) {
    document.getElementById("last-updated").textContent = timestamp;
}

function updateSummary(cards) {
    document.getElementById("total-containers").textContent =
        cards[0].value;

    document.getElementById("running-containers").textContent =
        cards[1].value;

    document.getElementById("stopped-containers").textContent =
        cards[2].value;
}

function updateRunningContainers(containers) {
    const table = document.getElementById(
        "running-container-table"
    );

    table.innerHTML = "";

    containers.forEach(container => {
        const row = document.createElement("tr");

        row.id = "container-" + container.name;

        row.innerHTML = `
            <td>${container.name}</td>
            <td><span class="badge bg-success">${container.status}</span></td>
            <td>${container.cpu}</td>
            <td>${container.memory}</td>
            <td>${container.restart}</td>
            <td>${container.uptime}</td>
        `;

        table.appendChild(row);
    });
}

function updateStoppedContainers(containers) {
    const table = document.getElementById(
        "stopped-container-table"
    );

    table.innerHTML = "";

    containers.forEach(container => {
        const row = document.createElement("tr");

        row.id = "container-" + container.name;

        row.innerHTML = `
            <td>${container.name}</td>
            <td><span class="badge bg-secondary">${container.status}</span></td>
            <td>${container.reason}</td>
            <td>${container.restart}</td>
        `;

        table.appendChild(row);
    });
}

document.addEventListener(
    "DOMContentLoaded",
    loadStatistics
);
