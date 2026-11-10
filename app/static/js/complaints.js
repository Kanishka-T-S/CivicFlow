(() => {
  const form = document.querySelector("#tracking-code-form");
  const codeInput = document.querySelector("#tracking-code");
  const message = document.querySelector("#dashboard-message");
  const complaintList = document.querySelector("#complaint-list");
  const detailPanel = document.querySelector("#complaint-detail");
  const complaintFields = document.querySelector("#complaint-fields");
  const historyList = document.querySelector("#complaint-history");
  const forgetCode = document.querySelector("#forget-tracking-code");
  if (!form) return;

  let trackingCode = "";

  function showMessage(text, isError = false) {
    message.textContent = text;
    message.classList.toggle("is-error", isError);
    message.hidden = !text;
  }

  async function api(path) {
    const response = await fetch(path, {
      headers: { Authorization: `Bearer ${trackingCode}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error?.message || "The request could not be completed.");
    }
    return payload;
  }

  function renderList(complaints) {
    complaintList.replaceChildren();
    if (!complaints.length) {
      const empty = document.createElement("p");
      empty.textContent = "No complaints were found for this tracking code.";
      complaintList.append(empty);
      return;
    }
    for (const complaint of complaints) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "complaint-list-item";
      button.innerHTML = "<strong></strong><span></span><span></span>";
      button.querySelector("strong").textContent = complaint.complaint_id;
      button.querySelectorAll("span")[0].textContent = complaint.category;
      button.querySelectorAll("span")[1].textContent = complaint.status;
      button.addEventListener("click", () => loadDetails(complaint.complaint_id));
      complaintList.append(button);
    }
  }

  async function loadDetails(id) {
    try {
      const complaint = await api(`/api/v1/complaints/${encodeURIComponent(id)}`);
      complaintFields.replaceChildren();
      for (const [label, value] of [
        ["Complaint ID", complaint.complaint_id],
        ["Category", complaint.category],
        ["Description", complaint.description],
        ["Location", complaint.location],
        ["Submitted", complaint.submitted_at],
        ["Current status", complaint.status],
        ["Last updated", complaint.last_updated_at],
      ]) {
        const row = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = `${label}: `;
        row.append(strong, document.createTextNode(value));
        complaintFields.append(row);
      }
      historyList.replaceChildren();
      for (const item of complaint.history) {
        const entry = document.createElement("li");
        const status = item.previous_status
          ? `${item.previous_status} → ${item.new_status}`
          : item.new_status;
        entry.textContent = `${item.updated_at} — ${status}${item.remarks ? `: ${item.remarks}` : ""}`;
        historyList.append(entry);
      }
      detailPanel.hidden = false;
      showMessage("");
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  async function loadComplaints() {
    trackingCode = codeInput.value.trim();
    if (!trackingCode) {
      showMessage("Enter your private tracking code.", true);
      return;
    }
    try {
      const result = await api("/api/v1/complaints");
      localStorage.setItem("civicflowTrackingCode", trackingCode);
      renderList(result.complaints);
      detailPanel.hidden = true;
      showMessage("");
    } catch (error) {
      showMessage(error.message, true);
      complaintList.replaceChildren();
      detailPanel.hidden = true;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadComplaints();
  });

  forgetCode.addEventListener("click", () => {
    localStorage.removeItem("civicflowTrackingCode");
    trackingCode = "";
    codeInput.value = "";
    complaintList.replaceChildren();
    detailPanel.hidden = true;
    showMessage("The tracking code was removed from this browser.");
  });

  const savedCode = localStorage.getItem("civicflowTrackingCode");
  if (savedCode) {
    codeInput.value = savedCode;
    loadComplaints();
  }
})();
