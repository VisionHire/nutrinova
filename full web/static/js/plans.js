// Plans page – Razorpay integration (exact original logic)
document.addEventListener("DOMContentLoaded", function () {
  // Get CSRF token from window (set in template)
  const csrfToken = window.csrfToken;

  // Modal functions (exactly as in original)
  window.showPhoneModal = function (planType) {
    document.getElementById("selectedPlan").value = planType;
    document.getElementById("phoneModal").style.display = "block";
    document.getElementById("phoneNumber").value = "";
    document.getElementById("phoneNumber").focus();
  };

  window.closeModal = function () {
    document.getElementById("phoneModal").style.display = "none";
    document.getElementById("modalSubmitBtn").disabled = false;
    document.getElementById("modalSubmitBtn").textContent =
      "Proceed to Payment";
  };

  // Close modal if user clicks outside
  window.onclick = function (event) {
    const modal = document.getElementById("phoneModal");
    if (event.target == modal) {
      closeModal();
    }
  };

  // Original initiatePayment function (without phone)
  window.initiatePayment = function (planType) {
    document.getElementById("loadingOverlay").style.display = "flex";

    fetch("/razorpay/create-order", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ plan_type: planType }),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw err;
          });
        }
        return response.json();
      })
      .then((data) => {
        if (data.status === "success") {
          document.getElementById("loadingOverlay").style.display = "none";

          const options = {
            key: data.key_id,
            amount: data.amount,
            currency: data.currency,
            name: data.name,
            description: data.description,
            order_id: data.order_id,
            prefill: {
              name: data.prefill.name,
              email: data.prefill.email,
            },
            theme: { color: data.theme.color },
            handler: function (response) {
              const form = document.createElement("form");
              form.method = "POST";
              form.action = "/razorpay/success";
              form.style.display = "none";

              const razorpayPaymentId = document.createElement("input");
              razorpayPaymentId.type = "hidden";
              razorpayPaymentId.name = "razorpay_payment_id";
              razorpayPaymentId.value = response.razorpay_payment_id;
              form.appendChild(razorpayPaymentId);

              const razorpayOrderId = document.createElement("input");
              razorpayOrderId.type = "hidden";
              razorpayOrderId.name = "razorpay_order_id";
              razorpayOrderId.value = response.razorpay_order_id;
              form.appendChild(razorpayOrderId);

              const razorpaySignature = document.createElement("input");
              razorpaySignature.type = "hidden";
              razorpaySignature.name = "razorpay_signature";
              razorpaySignature.value = response.razorpay_signature;
              form.appendChild(razorpaySignature);

              const csrfInput = document.createElement("input");
              csrfInput.type = "hidden";
              csrfInput.name = "csrf_token";
              csrfInput.value = csrfToken;
              form.appendChild(csrfInput);

              document.body.appendChild(form);
              form.submit();
            },
            modal: {
              ondismiss: function () {
                window.location.href = "/plans?payment=cancelled";
              },
            },
          };
          const razorpay = new Razorpay(options);
          razorpay.open();
        } else {
          alert(
            "Payment initiation failed: " + (data.error || "Unknown error"),
          );
          document.getElementById("loadingOverlay").style.display = "none";
        }
      })
      .catch((error) => {
        console.error("Error:", error);
        alert(
          "Failed to initiate payment. Please try again. " +
            (error.error || ""),
        );
        document.getElementById("loadingOverlay").style.display = "none";
      });
  };

  // Original submitPhoneNumber function
  window.submitPhoneNumber = function () {
    const phone = document.getElementById("phoneNumber").value.trim();
    const planType = document.getElementById("selectedPlan").value;
    const submitBtn = document.getElementById("modalSubmitBtn");

    if (!phone) {
      alert("Please enter your phone number");
      return;
    }
    if (!/^\d{10}$/.test(phone)) {
      alert("Please enter a valid 10-digit phone number");
      return;
    }

    submitBtn.textContent = "Processing...";
    submitBtn.disabled = true;
    closeModal();

    document.getElementById("loadingOverlay").style.display = "flex";

    fetch("/razorpay/create-order", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ plan_type: planType, phone: phone }),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw err;
          });
        }
        return response.json();
      })
      .then((data) => {
        if (data.status === "success") {
          document.getElementById("loadingOverlay").style.display = "none";

          const options = {
            key: data.key_id,
            amount: data.amount,
            currency: data.currency,
            name: data.name,
            description: data.description,
            order_id: data.order_id,
            prefill: {
              name: data.prefill.name,
              email: data.prefill.email,
              contact: phone,
            },
            theme: { color: data.theme.color },
            handler: function (response) {
              const form = document.createElement("form");
              form.method = "POST";
              form.action = "/razorpay/success";
              form.style.display = "none";

              const razorpayPaymentId = document.createElement("input");
              razorpayPaymentId.type = "hidden";
              razorpayPaymentId.name = "razorpay_payment_id";
              razorpayPaymentId.value = response.razorpay_payment_id;
              form.appendChild(razorpayPaymentId);

              const razorpayOrderId = document.createElement("input");
              razorpayOrderId.type = "hidden";
              razorpayOrderId.name = "razorpay_order_id";
              razorpayOrderId.value = response.razorpay_order_id;
              form.appendChild(razorpayOrderId);

              const razorpaySignature = document.createElement("input");
              razorpaySignature.type = "hidden";
              razorpaySignature.name = "razorpay_signature";
              razorpaySignature.value = response.razorpay_signature;
              form.appendChild(razorpaySignature);

              const csrfInput = document.createElement("input");
              csrfInput.type = "hidden";
              csrfInput.name = "csrf_token";
              csrfInput.value = csrfToken;
              form.appendChild(csrfInput);

              document.body.appendChild(form);
              form.submit();
            },
            modal: {
              ondismiss: function () {
                window.location.href = "/plans?payment=cancelled";
              },
            },
          };
          const razorpay = new Razorpay(options);
          razorpay.open();
        } else {
          alert(
            "Payment initiation failed: " + (data.error || "Unknown error"),
          );
          document.getElementById("loadingOverlay").style.display = "none";
        }
      })
      .catch((error) => {
        console.error("Error:", error);
        alert(
          "Failed to initiate payment. Please try again. " +
            (error.error || ""),
        );
        document.getElementById("loadingOverlay").style.display = "none";
      });
  };

  // Handle payment status from URL
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("payment") === "cancelled") {
    alert("Payment was cancelled");
  }
});
