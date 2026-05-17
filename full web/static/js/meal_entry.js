// ======================================
// 🌿 NutriTrack - Meal Entry (Server-side Version)
// ======================================

document.addEventListener("DOMContentLoaded", () => {
  const addItemBtn = document.getElementById("addItem");
  const container = document.getElementById("itemContainer");
  const saveMealBtn = document.getElementById("saveMealBtn");
  const toggleSavedMeals = document.getElementById("toggleSavedMeals");
  const savedMealsContainer = document.getElementById("savedMealsContainer");
  const mealTypeSelect = document.getElementById("mealType");

  if (savedMealsContainer) savedMealsContainer.style.display = "none";

  let savedMealsCache = [];

  // ---------------------------
  // Toast Notification
  // ---------------------------
  function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast-alert ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add("show"), 100);
    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 400);
    }, 2500);
  }

  // ---------------------------
  // Add Item Row
  // ---------------------------
  addItemBtn?.addEventListener("click", () => {
    if (!container) return;

    const div = document.createElement("div");
    div.classList.add("item-row");

    div.innerHTML = `
      <input type="text" name="item_name[]" class="input-text" placeholder="Enter food item" required>
      <input type="number" name="item_weight[]" class="input-text" placeholder="Weight (g)" required>
      <button type="button" class="btn-remove">✕</button>
    `;

    container.appendChild(div);
  });

  // ---------------------------
  // Remove Item Row (safe)
  // ---------------------------
  container?.addEventListener("click", (e) => {
    if (e.target.classList.contains("btn-remove")) {
      const row = e.target.closest(".item-row");
      if (row) row.remove();
    }
  });

  // ---------------------------
  // Load Saved Meals
  // ---------------------------
  async function loadSavedMeals() {
    if (!savedMealsContainer) return;

    try {
      const res = await fetch("/api/saved-meals?days=30");
      if (!res.ok) throw new Error("Failed to load saved meals");

      let data;
      try {
        data = await res.json();
      } catch {
        throw new Error("Invalid JSON response");
      }

      savedMealsCache = data;
      renderSavedMealsList();
    } catch (err) {
      console.error("Error loading saved meals:", err);
      savedMealsContainer.innerHTML = `<p class="empty-msg">Unable to load saved meals.</p>`;
    }
  }

  // ---------------------------
  // Render Meals (SAFE DOM)
  // ---------------------------
  function renderSavedMealsList() {
    if (!savedMealsContainer) return;

    savedMealsContainer.innerHTML = "";

    if (!savedMealsCache.length) {
      savedMealsContainer.innerHTML = `<p class="empty-msg">No saved meals in the last 30 days.</p>`;
      return;
    }

    savedMealsCache.forEach((meal) => {
      const div = document.createElement("div");
      div.classList.add("saved-meal-entry");

      const head = document.createElement("div");
      head.classList.add("meal-entry-head");

      const strong = document.createElement("strong");
      strong.textContent = meal.meal_type || "Meal";

      const count = (meal.items || []).length;
      const date = meal.date || "Unknown Date";

      const span = document.createElement("span");
      span.classList.add("count");
      span.textContent = `(${count} items)`;

      head.appendChild(strong);
      head.append(` — ${date} `);
      head.appendChild(span);

      const actions = document.createElement("div");
      actions.classList.add("meal-entry-actions");

      const btn = document.createElement("button");
      btn.classList.add("btn-danger", "deleteMealBtn");
      btn.dataset.id = meal.id;
      btn.textContent = "🗑️ Delete";

      actions.appendChild(btn);
      div.appendChild(head);
      div.appendChild(actions);

      savedMealsContainer.appendChild(div);
    });

    // Delete handler
    savedMealsContainer.querySelectorAll(".deleteMealBtn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const id = e.target.dataset.id;
        if (!id) return;

        if (!confirm("Delete this saved meal?")) return;

        try {
          const res = await fetch(`/api/saved-meals/${id}`, {
            method: "DELETE",
          });

          if (!res.ok) throw new Error("Delete failed");

          showToast("🗑️ Meal deleted successfully.");
          await loadSavedMeals();
        } catch (err) {
          console.error(err);
          showToast("❌ Failed to delete meal.", "error");
        }
      });
    });
  }

  // ---------------------------
  // Save Meal (UX Improved)
  // ---------------------------
  saveMealBtn?.addEventListener("click", async () => {
    const mealType = mealTypeSelect?.value || "General";

    const items = [
      ...document.querySelectorAll('input[name="item_name[]"]'),
    ].map((i) => i.value.trim());

    const weights = [
      ...document.querySelectorAll('input[name="item_weight[]"]'),
    ].map((i) => i.value.trim());

    if (items.some((i) => !i) || weights.some((w) => !w)) {
      showToast("⚠️ Fill all items and weights.", "warning");
      return;
    }

    const payloadItems = items.map((n, i) => ({
      name: n,
      weight: parseFloat(weights[i]) || 0,
    }));

    try {
      saveMealBtn.disabled = true;
      saveMealBtn.textContent = "Saving...";

      const res = await fetch("/api/saved-meals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          meal_type: mealType,
          items: payloadItems,
        }),
      });

      let data;
      try {
        data = await res.json();
      } catch {
        throw new Error("Invalid JSON");
      }

      if (!res.ok || data.error) {
        showToast(data.error || "Save failed", "error");
        return;
      }

      showToast(`✅ ${mealType} saved!`);

      if (savedMealsContainer) {
        savedMealsContainer.style.display = "block";
      }

      if (toggleSavedMeals) {
        toggleSavedMeals.textContent = "📁 Hide Saved Meals";
      }

      await loadSavedMeals();
    } catch (err) {
      console.error(err);
      showToast("❌ Error saving meal.", "error");
    } finally {
      saveMealBtn.disabled = false;
      saveMealBtn.textContent = "Save Meal";
    }
  });

  // ---------------------------
  // Toggle Panel
  // ---------------------------
  toggleSavedMeals?.addEventListener("click", () => {
    if (!savedMealsContainer) return;

    const isHidden =
      savedMealsContainer.style.display === "none" ||
      savedMealsContainer.style.display === "";

    savedMealsContainer.style.display = isHidden ? "block" : "none";

    if (toggleSavedMeals) {
      toggleSavedMeals.textContent = isHidden
        ? "📁 Hide Saved Meals"
        : "📂 Show Saved Meals";
    }

    if (isHidden) loadSavedMeals();
  });

  loadSavedMeals();
});

// ======================================
// 🍎 Food Autocomplete (Optimized)
// ======================================

(async function setupFoodSearch() {
  try {
    const res = await fetch("/api/get_nutrition_data");
    if (!res.ok) throw new Error("Food data failed");

    const foods = await res.json();
    const foodNames = Object.keys(foods).sort();

    const createSuggestionBox = (input) => {
      const list = document.createElement("div");
      list.classList.add("suggestion-box");
      input.parentNode.appendChild(list);
      return list;
    };

    document.addEventListener("input", (e) => {
      if (!e.target.matches('input[name="item_name[]"]')) return;

      const input = e.target;
      const val = input.value.toLowerCase();

      const box =
        input.parentNode.querySelector(".suggestion-box") ||
        createSuggestionBox(input);

      if (!val) {
        box.innerHTML = "";
        return;
      }

      const matches = foodNames.filter((n) => n.includes(val)).slice(0, 7);

      box.innerHTML = matches
        .map((m) => `<div class="suggestion-item">${m}</div>`)
        .join("");
    });

    // Event delegation (FIXED)
    document.addEventListener("click", (e) => {
      if (e.target.classList.contains("suggestion-item")) {
        const box = e.target.closest(".suggestion-box");
        const input = box?.parentNode.querySelector(
          'input[name="item_name[]"]',
        );

        if (input) input.value = e.target.textContent;
        if (box) box.innerHTML = "";
      }

      document.querySelectorAll(".suggestion-box").forEach((box) => {
        if (!box.contains(e.target)) box.innerHTML = "";
      });
    });
  } catch (err) {
    console.error("Autocomplete failed:", err);
  }
})();
