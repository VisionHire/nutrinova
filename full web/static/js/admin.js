// ================================
// 🌿 NutriTrack Admin JS
// ================================

// Modal elements
const modal = document.getElementById("editModal");
const editForm = document.getElementById("editForm");
let currentFoodId = null;

// 🔹 Open modal and fill with selected row data
function openEditModal(button) {
  const row = button.closest("tr");
  currentFoodId = row.dataset.id;

  document.getElementById("editName").value = row.dataset.name;
  document.getElementById("editCalories").value = row.dataset.calories;
  document.getElementById("editProtein").value = row.dataset.protein;
  document.getElementById("editCarbs").value = row.dataset.carbs;
  document.getElementById("editFats").value = row.dataset.fats;

  // Parse vitamins and minerals JSON safely
  try {
    const vits = JSON.parse(row.dataset.vitamins || "{}");
    const mins = JSON.parse(row.dataset.minerals || "{}");
    document.getElementById("editVitamins").value = JSON.stringify(vits, null, 2);
    document.getElementById("editMinerals").value = JSON.stringify(mins, null, 2);
  } catch (err) {
    document.getElementById("editVitamins").value = row.dataset.vitamins || "{}";
    document.getElementById("editMinerals").value = row.dataset.minerals || "{}";
  }

  modal.style.display = "block";
}

// 🔹 Close modal
function closeModal() {
  modal.style.display = "none";
  currentFoodId = null;
}

// 🔹 Submit edited data
editForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentFoodId) return alert("Food ID missing.");

  const formData = new FormData(editForm);

  const response = await fetch(`/admin/food/update/${currentFoodId}`, {
    method: "POST",
    body: formData,
  });

  if (response.ok) {
    alert("✅ Food updated successfully!");
    closeModal();
    location.reload(); // refresh page to reflect changes
  } else {
    const errText = await response.text();
    alert("❌ Error updating food: " + errText);
  }
});

// 🔹 Close modal on outside click
window.onclick = function (event) {
  if (event.target === modal) closeModal();
};

// 🔹 Close modal on ESC key
window.addEventListener("keydown", function (e) {
  if (e.key === "Escape") closeModal();
});

// ================================
// 🔍 User Search Filter (NEW FEATURE)
// ================================
document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("userSearch");
  const userTable = document.querySelector(".user-table tbody");

  if (searchInput && userTable) {
    searchInput.addEventListener("keyup", () => {
      const filter = searchInput.value.toLowerCase();
      const rows = userTable.querySelectorAll("tr");

      rows.forEach((row) => {
        const name = row.cells[0]?.textContent.toLowerCase() || "";
        const email = row.cells[1]?.textContent.toLowerCase() || "";
        row.style.display =
          name.includes(filter) || email.includes(filter) ? "" : "none";
      });
    });
  }
});

// ================================
// 🥗 ADD FOOD FORM HANDLER (Improved + Duplicate Safe + Auto-refresh)
// ================================
document.addEventListener("DOMContentLoaded", () => {
  const addFoodForm = document.querySelector(".food-form");
  if (!addFoodForm) return;

  addFoodForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const formData = new FormData(addFoodForm);

    try {
      const res = await fetch("/admin/food/add", {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });

      if (!res.ok) {
        alert("❌ Failed to add food. Server error.");
        return;
      }

      const data = await res.json();

      if (data.status === "duplicate") {
        alert(data.message || "⚠️ This food already exists.");
        return;
      }

      if (data.status === "success") {
        alert("✅ Food added successfully and foods.json updated!");

        // 🔄 Auto-refresh the food table dynamically (no full reload)
        const tbody = document.querySelector(".food-table tbody");
        if (tbody) {
          const name = addFoodForm.querySelector('[name="name"]').value;
          const calories = addFoodForm.querySelector('[name="calories"]').value;
          const protein = addFoodForm.querySelector('[name="protein"]').value;
          const carbs = addFoodForm.querySelector('[name="carbohydrates"]').value;
          const fats = addFoodForm.querySelector('[name="fats"]').value;

          const newRow = document.createElement("tr");
          newRow.innerHTML = `
            <td>${name}</td>
            <td>${calories}</td>
            <td>${protein}</td>
            <td>${carbs}</td>
            <td>${fats}</td>
            <td><em>Just added</em></td>
          `;
          tbody.appendChild(newRow);
        }

        addFoodForm.reset(); // clear form fields
      } else {
        alert("⚠️ Unexpected response from server.");
      }
    } catch (err) {
      console.error("Add food error:", err);
      alert("⚠️ Could not add food. Check console for details.");
    }
  });
});
