(() => {
  const form = document.querySelector("#audio-form");
  const fileInput = document.querySelector("#audio-file");
  const uploadArea = document.querySelector("#upload-area");
  const fileName = document.querySelector("#file-name");
  const fileHint = document.querySelector("#file-hint");
  const uploadError = document.querySelector("#upload-error");
  const submitAudio = document.querySelector("#submit-audio");
  const resultPanel = document.querySelector("#request-result");
  const transcriptText = document.querySelector("#transcript-text");
  const requestStatus = document.querySelector("#request-status");
  const requestCategory = document.querySelector("#request-category");
  const requestSummary = document.querySelector("#request-summary");
  const requestLocation = document.querySelector("#request-location");
  const nextStepMessage = document.querySelector("#next-step-message");
  const followupForm = document.querySelector("#followup-form");
  const followupText = document.querySelector("#followup-text");
  const submitFollowup = document.querySelector("#submit-followup");
  const confirmButton = document.querySelector("#confirm-request");
  const workflowError = document.querySelector("#workflow-error");
  const confirmationNote = document.querySelector("#confirmation-note");
  const complaintRegistration = document.querySelector("#complaint-registration");
  const complaintId = document.querySelector("#complaint-id");
  const trackingCodeDisplay = document.querySelector("#tracking-code-display");
  const copyTrackingCode = document.querySelector("#copy-tracking-code");

  if (!form || !fileInput) return;

  const maxBytes = Number(document.body.dataset.maxAudioBytes) || 10_000_000;
  const acceptedExtensions = new Set(["m4a", "mp3", "wav"]);
  const statusLabels = {
    needs_details: "More details needed",
    ready_for_confirmation: "Ready to confirm",
    confirmed: "Confirmed locally",
    Pending: "Pending",
    "In Progress": "In progress",
    Resolved: "Resolved",
    Rejected: "Rejected",
  };
  let requestId = null;
  let transcript = "";

  function showError(element, message) {
    element.textContent = message;
    element.hidden = false;
  }

  function clearError(element) {
    element.textContent = "";
    element.hidden = true;
  }

  function selectedFile() {
    return fileInput.files && fileInput.files.length ? fileInput.files[0] : null;
  }

  function validateFile(file) {
    if (!file) return "Choose an audio file to continue.";
    const extension = file.name.split(".").pop().toLowerCase();
    if (!acceptedExtensions.has(extension)) return "Choose an M4A, MP3, or WAV audio file.";
    if (file.size === 0) return "This audio file is empty. Choose another file.";
    if (file.size > maxBytes) return "This file is too large. Choose an audio file under 10 MB.";
    return "";
  }

  function formatCategory(category) {
    return category
      ? category.charAt(0).toUpperCase() + category.slice(1)
      : "Other";
  }

  function renderRequest(result) {
    requestId = result.request_id;
    const workflowStatus = result.workflow_status || result.status;
    transcriptText.textContent = transcript;
    requestCategory.textContent = formatCategory(result.category);
    requestSummary.textContent = result.summary || "Details pending";
    requestLocation.textContent = result.details?.location || "Needed";

    const label = statusLabels[result.complaint_status] || statusLabels[result.status] || "In progress";
    requestStatus.textContent = label;
    requestStatus.dataset.status = result.complaint_status || result.status || "";
    resultPanel.hidden = false;
    followupForm.hidden = workflowStatus !== "needs_details";
    confirmButton.hidden = workflowStatus !== "ready_for_confirmation";
    confirmationNote.hidden = workflowStatus !== "confirmed";
    complaintRegistration.hidden = workflowStatus !== "confirmed" || !result.complaint_id;
    if (result.tracking_code) {
      localStorage.setItem("civicflowTrackingCode", result.tracking_code);
      trackingCodeDisplay.textContent = result.tracking_code;
    }
    if (result.complaint_id) complaintId.textContent = result.complaint_id;
    clearError(workflowError);

    if (workflowStatus === "needs_details") {
      nextStepMessage.textContent = result.question || "Add the missing details to continue.";
    } else if (workflowStatus === "ready_for_confirmation") {
      nextStepMessage.textContent = "Review the transcript and details above, then confirm your request.";
    } else {
      nextStepMessage.textContent = "Your request has been confirmed locally.";
    }

    if (workflowStatus === "needs_details") {
      followupText.focus();
    } else {
      resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function readResponse(response) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("The service returned an unexpected response. Please try again.");
    }
    if (!response.ok) {
      throw new Error(payload.error?.message || "The request could not be completed. Please try again.");
    }
    return payload;
  }

  fileInput.addEventListener("change", () => {
    clearError(uploadError);
    const file = selectedFile();
    fileName.textContent = file ? file.name : "Choose an audio recording";
    fileHint.textContent = file ? "Selected and ready to upload" : "or drag and drop it here";
    if (file) {
      const error = validateFile(file);
      if (error) showError(uploadError, error);
    }
  });

  for (const eventName of ["dragenter", "dragover"]) {
    uploadArea.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadArea.classList.add("is-dragging");
    });
  }

  for (const eventName of ["dragleave", "drop"]) {
    uploadArea.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadArea.classList.remove("is-dragging");
    });
  }

  uploadArea.addEventListener("drop", (event) => {
    const [file] = event.dataTransfer.files;
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError(uploadError);
    const file = selectedFile();
    const validationError = validateFile(file);
    if (validationError) {
      showError(uploadError, validationError);
      return;
    }

    const buttonLabel = submitAudio.querySelector("span");
    buttonLabel.textContent = "Transcribing audio…";
    submitAudio.disabled = true;

    try {
      const response = await fetch("/api/v1/requests", {
        method: "POST",
        body: new FormData(form),
      });
      const result = await readResponse(response);
      transcript = result.transcript || "";
      renderRequest(result);
    } catch (error) {
      showError(uploadError, error.message);
    } finally {
      buttonLabel.textContent = "Transcribe & continue";
      submitAudio.disabled = false;
    }
  });

  followupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError(workflowError);
    const text = followupText.value.trim();
    if (!requestId || !text) {
      showError(workflowError, "Enter the missing details to continue.");
      return;
    }
    submitFollowup.disabled = true;
    try {
      const response = await fetch(`/api/v1/requests/${encodeURIComponent(requestId)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const result = await readResponse(response);
      followupText.value = "";
      renderRequest(result);
    } catch (error) {
      showError(workflowError, error.message);
    } finally {
      submitFollowup.disabled = false;
    }
  });

  confirmButton.addEventListener("click", async () => {
    if (!requestId) return;
    clearError(workflowError);
    confirmButton.disabled = true;
    try {
      const response = await fetch(`/api/v1/requests/${encodeURIComponent(requestId)}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tracking_code: localStorage.getItem("civicflowTrackingCode") || undefined,
        }),
      });
      const result = await readResponse(response);
      renderRequest(result);
    } catch (error) {
      showError(workflowError, error.message);
    } finally {
      confirmButton.disabled = false;
    }
  });

  copyTrackingCode.addEventListener("click", async () => {
    const trackingCode = localStorage.getItem("civicflowTrackingCode");
    if (!trackingCode) return;
    try {
      await navigator.clipboard.writeText(trackingCode);
      copyTrackingCode.textContent = "Copied";
    } catch {
      copyTrackingCode.textContent = "Select the code above";
      trackingCodeDisplay.focus();
    }
  });
})();
