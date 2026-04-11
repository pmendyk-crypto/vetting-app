(function () {
  function ensureModal() {
    let backdrop = document.getElementById("confirmModalBackdrop");
    if (backdrop) {
      return backdrop;
    }

    backdrop = document.createElement("div");
    backdrop.id = "confirmModalBackdrop";
    backdrop.className = "confirm-modal-backdrop";
    backdrop.innerHTML = [
      '<div class="confirm-modal-card" role="dialog" aria-modal="true" aria-labelledby="confirmModalTitle">',
      '  <h3 id="confirmModalTitle" class="confirm-modal-title">Confirm Action</h3>',
      '  <p id="confirmModalCopy" class="confirm-modal-copy"></p>',
      '  <div class="confirm-modal-actions">',
      '    <button type="button" id="confirmModalCancel" class="btn secondary">Cancel</button>',
      '    <button type="button" id="confirmModalConfirm" class="btn btn-danger">Confirm</button>',
      "  </div>",
      "</div>",
    ].join("");
    document.body.appendChild(backdrop);

    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) {
        closeModal();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && backdrop.classList.contains("open")) {
        closeModal();
      }
    });
    document.getElementById("confirmModalCancel").addEventListener("click", closeModal);
    return backdrop;
  }

  let pendingConfirm = null;

  function closeModal() {
    const backdrop = ensureModal();
    backdrop.classList.remove("open");
    pendingConfirm = null;
  }

  function openModal(options) {
    const backdrop = ensureModal();
    const title = document.getElementById("confirmModalTitle");
    const copy = document.getElementById("confirmModalCopy");
    const confirmButton = document.getElementById("confirmModalConfirm");

    title.textContent = options.title || "Confirm Action";
    copy.textContent = options.message || "Are you sure you want to continue?";
    confirmButton.textContent = options.confirmLabel || "Confirm";
    confirmButton.className = "btn " + (options.confirmClass || "btn-danger");

    confirmButton.onclick = function () {
      const callback = pendingConfirm;
      closeModal();
      if (callback) {
        callback();
      }
    };

    pendingConfirm = options.onConfirm || null;
    backdrop.classList.add("open");
  }

  function interceptConfirmedForm(form) {
    if (!form || form.dataset.confirmHandled === "1") {
      return;
    }
    form.dataset.confirmHandled = "1";
    form.addEventListener("submit", function (event) {
      if (form.dataset.confirmBypassed === "1") {
        delete form.dataset.confirmBypassed;
        return;
      }
      const message = form.dataset.confirmMessage;
      if (!message) {
        return;
      }
      event.preventDefault();
      openModal({
        title: form.dataset.confirmTitle || "Confirm Action",
        message: message,
        confirmLabel: form.dataset.confirmLabel || "Delete",
        confirmClass: form.dataset.confirmClass || "btn-danger",
        onConfirm: function () {
          form.dataset.confirmBypassed = "1";
          if (form.requestSubmit) {
            form.requestSubmit();
          } else {
            form.submit();
          }
        },
      });
    });
  }

  function init() {
    document.querySelectorAll("form[data-confirm-message]").forEach(interceptConfirmedForm);
  }

  window.showConfirmModal = function (options) {
    openModal(options || {});
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
