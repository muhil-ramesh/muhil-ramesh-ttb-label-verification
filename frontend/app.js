const form = document.querySelector("#verify-form");
const imageInput = document.querySelector("#image-input");
const imagePreview = document.querySelector("#image-preview");
const fileName = document.querySelector("#file-name");
const formMessage = document.querySelector("#form-message");
const submitButton = document.querySelector("#submit-button");
const resultPanel = document.querySelector("#result-panel");

const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageBytes = 8 * 1024 * 1024;
const requestTimeoutMs = 16000;

const fields = [
  ["brand_name", document.querySelector("#brand-name")],
  ["product_class", document.querySelector("#product-class")],
  ["producer_name", document.querySelector("#producer-name")],
  ["country_of_origin", document.querySelector("#country-origin")],
  ["abv", document.querySelector("#abv")],
  ["net_contents", document.querySelector("#net-contents")],
  ["government_warning", document.querySelector("#government-warning")],
];

const fieldLabels = {
  brand_name: "Brand Name",
  product_class: "Product Type",
  producer_name: "Producer Name",
  country_of_origin: "Country of Origin",
  abv: "Alcohol Content",
  net_contents: "Net Contents",
  government_warning: "Government Warning",
};

function selectedImage() {
  return imageInput.files && imageInput.files.length > 0 ? imageInput.files[0] : null;
}

function allFieldsFilled() {
  return fields.every(([, input]) => input.value.trim().length > 0);
}

function formReady() {
  const file = selectedImage();
  return Boolean(file && allowedTypes.has(file.type) && file.size > 0 && allFieldsFilled());
}

function updateFormState() {
  submitButton.disabled = !formReady();
  if (!selectedImage() || !allFieldsFilled()) {
    setFormMessage("Choose an image and fill in all fields to check the label.");
  } else if (!allowedTypes.has(selectedImage().type)) {
    setFormMessage("Use a JPEG, PNG, or WebP image.", true);
  } else if (selectedImage().size === 0) {
    setFormMessage("That image file is empty. Choose another image.", true);
  } else {
    setFormMessage("");
  }
}

function setFormMessage(message, isError = false, isLoading = false) {
  formMessage.textContent = message;
  formMessage.className = "form-message";
  if (isError) {
    formMessage.classList.add("form-message--error");
  }
  if (isLoading) {
    formMessage.classList.add("form-message--loading");
  }
}

function setLoading(isLoading) {
  for (const [, input] of fields) {
    input.disabled = isLoading;
  }
  imageInput.disabled = isLoading;
  submitButton.disabled = isLoading || !formReady();
  submitButton.textContent = isLoading ? "Reading label..." : "Check Label";
  if (isLoading) {
    setFormMessage("Reading label...", false, true);
  }
}

function applicationData() {
  const data = {};
  for (const [name, input] of fields) {
    data[name] = name === "government_warning" ? input.value : input.value.trim();
  }
  return data;
}

function validateBeforeSubmit() {
  const file = selectedImage();
  if (!file) {
    return "Choose a label image.";
  }
  if (!allowedTypes.has(file.type)) {
    return "Use a JPEG, PNG, or WebP image.";
  }
  if (file.size === 0) {
    return "That image file is empty. Choose another image.";
  }
  if (file.size > maxImageBytes) {
    return "Use an image smaller than 8 MB.";
  }
  if (!allFieldsFilled()) {
    return "Fill in every field before checking the label.";
  }
  return "";
}

imageInput.addEventListener("change", () => {
  const file = selectedImage();
  if (!file) {
    fileName.textContent = "JPEG, PNG, or WebP";
    imagePreview.hidden = true;
    imagePreview.removeAttribute("src");
    updateFormState();
    return;
  }

  fileName.textContent = file.name;
  if (allowedTypes.has(file.type) && file.size > 0) {
    imagePreview.src = URL.createObjectURL(file);
    imagePreview.hidden = false;
  } else {
    imagePreview.hidden = true;
    imagePreview.removeAttribute("src");
  }
  updateFormState();
});

for (const [, input] of fields) {
  input.addEventListener("input", updateFormState);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const validationMessage = validateBeforeSubmit();
  if (validationMessage) {
    setFormMessage(validationMessage, true);
    return;
  }

  const formData = new FormData();
  formData.append("image", selectedImage());
  formData.append("application_data", JSON.stringify(applicationData()));

  resultPanel.hidden = true;
  resultPanel.innerHTML = "";
  setLoading(true);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    const response = await fetch("/verify", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    const data = await response.json();
    if (!response.ok) {
      throw new Error(readableError(data));
    }

    renderResults(data);
    setFormMessage("");
  } catch (error) {
    if (error.name === "AbortError") {
      renderError("The label took too long to read. Try a clearer or smaller image.");
    } else {
      renderError(error.message || "The label could not be checked. Please try again.");
    }
  } finally {
    clearTimeout(timeoutId);
    setLoading(false);
    updateFormState();
  }
});

function readableError(data) {
  if (data && data.error && data.error.message) {
    return data.error.message;
  }
  return "The label could not be checked. Please try again.";
}

function renderError(message) {
  resultPanel.hidden = false;
  resultPanel.innerHTML = `
    <div class="error-panel">
      <h2 class="error-panel__title">Could not check label</h2>
      <p class="error-panel__message">${escapeHtml(message)}</p>
    </div>
  `;
  focusResults();
}

function renderResults(data) {
  const approved = data.verdict === "PASS";
  const verdictText = approved ? "APPROVED" : "NEEDS REVIEW";
  const verdictClass = approved ? "verdict--pass" : "verdict--review";
  const checkedSeconds = typeof data.latency_ms === "number" ? (data.latency_ms / 1000).toFixed(1) : "0.0";
  const fieldsHtml = (data.fields || []).map(renderFieldResult).join("");

  resultPanel.hidden = false;
  resultPanel.innerHTML = `
    <div class="verdict ${verdictClass}">
      <span class="verdict__label">${verdictText}</span>
      <span class="verdict__time">Checked in ${checkedSeconds} seconds</span>
    </div>
    <div class="results-list">
      ${fieldsHtml}
    </div>
  `;
  focusResults();
}

function renderFieldResult(result) {
  const passed = result.status === "PASS";
  const statusClass = passed ? "status-badge--pass" : "status-badge--fail";
  const cardClass = passed ? "field-result--pass" : "field-result--fail";
  const fieldName = fieldLabels[result.field] || result.field;
  const actual = result.actual || "Not found on the label";
  const details = passed ? renderPassDetails(actual) : renderFailDetails(result, actual);

  return `
    <article class="field-result ${cardClass}">
      <div class="field-result__header">
        <h3>${escapeHtml(fieldName)}</h3>
        <span class="status-badge ${statusClass}">${result.status}</span>
      </div>
      ${details}
    </article>
  `;
}

function renderPassDetails(actual) {
  return `
    <div class="comparison">
      <div>
        <span class="comparison__label">Found</span>
        <div class="comparison__value">${escapeHtml(actual)}</div>
      </div>
    </div>
  `;
}

function renderFailDetails(result, actual) {
  return `
    <div class="comparison">
      <div>
        <span class="comparison__label">Expected</span>
        <div class="comparison__value">${escapeHtml(result.expected || "")}</div>
      </div>
      <div>
        <span class="comparison__label">Found</span>
        <div class="comparison__value">${escapeHtml(actual)}</div>
      </div>
    </div>
    <p class="why-text">Why: ${escapeHtml(failureReason(result))}</p>
  `;
}

function failureReason(result) {
  if (result.field === "government_warning") {
    return "The government warning must match exactly, including capital letters, punctuation, spaces, and line breaks.";
  }
  if (!result.actual) {
    return "This was not found on the label.";
  }
  if (result.field === "abv" || result.field === "net_contents") {
    return "The amounts do not match.";
  }
  if (result.field === "country_of_origin") {
    return "The countries do not match.";
  }
  return "These do not match closely enough.";
}

function focusResults() {
  resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  resultPanel.focus({ preventScroll: true });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

updateFormState();
