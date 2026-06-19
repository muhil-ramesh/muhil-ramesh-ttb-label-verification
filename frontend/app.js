const statusBox = document.querySelector("#status-box");
const checkButton = document.querySelector("#check-button");

function setStatus(className, message) {
  statusBox.className = `status-box ${className}`;
  statusBox.textContent = message;
}

async function checkHealth() {
  setStatus("status-box--loading", "Checking server status...");

  try {
    const response = await fetch("/health", {
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`Health check failed with HTTP ${response.status}`);
    }

    const data = await response.json();
    setStatus("status-box--success", JSON.stringify(data, null, 2));
  } catch (error) {
    setStatus(
      "status-box--error",
      `The server did not respond correctly.\n\n${error.message}`,
    );
  }
}

checkButton.addEventListener("click", checkHealth);
checkHealth();
