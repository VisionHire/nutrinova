// =============================
// 🍽 NutriTrack Meal Planner (Integrated with planned meals)
// =============================

document.addEventListener("DOMContentLoaded", async () => {
  const tbody = document.querySelector("#mealTable tbody");
  const foodInput = document.getElementById("foodName");
  const suggestionBox = document.getElementById("mealSuggestionsBox");
  const addBtn = document.getElementById("addMealBtn");
  const mealType = document.getElementById("mealType");
  const weightInput = document.getElementById("weightInput");
  const unitSelect = document.getElementById("unitSelect");

  let foodIndex = [];
  let debounceTimer;

  // Unit conversion to grams
  const unitToGrams = {
    g: 1,
    kg: 1000,
    oz: 28.3495,
    lb: 453.592,
  };

  function convertToGrams(value, unit) {
    return value * (unitToGrams[unit] || 1);
  }

  // -----------------------------
  // Load foods from Flask JSON route
  // -----------------------------
  async function loadFoods() {
    try {
      const res = await fetch("/foods-json", { cache: "no-store" });
      const data = await res.json();
      foodIndex = Object.keys(data).map((name) => ({
        name: name.charAt(0).toUpperCase() + name.slice(1),
        calories: data[name].macronutrients?.calories || 0,
      }));
      console.log("✅ Loaded foods:", foodIndex.length, "items");
    } catch (err) {
      console.error("❌ Failed to load foods.json:", err);
    }
  }

  // -----------------------------
  // Show suggestions dynamically
  // -----------------------------
  function showSuggestions() {
    const query = foodInput.value.trim().toLowerCase();
    suggestionBox.innerHTML = "";

    if (!query) {
      suggestionBox.style.display = "none";
      return;
    }

    const matches = foodIndex
      .filter((f) => f.name.toLowerCase().includes(query))
      .slice(0, 8);

    if (matches.length === 0) {
      suggestionBox.style.display = "none";
      return;
    }

    matches.forEach((item) => {
      const div = document.createElement("div");
      div.textContent = `${item.name} (${item.calories} kcal/100g)`;
      div.addEventListener("click", () => selectFood(item));
      suggestionBox.appendChild(div);
    });

    suggestionBox.style.display = "block";
    const rect = foodInput.getBoundingClientRect();
    suggestionBox.style.top = `${foodInput.offsetHeight + 6}px`;
    suggestionBox.style.left = "0";
    suggestionBox.style.width = `${foodInput.offsetWidth}px`;
  }

  // -----------------------------
  // Select food → (no calorie autofill needed)
  // -----------------------------
  function selectFood(item) {
    foodInput.value = item.name;
    suggestionBox.style.display = "none";
  }

  // Hide dropdown if clicked elsewhere
  document.addEventListener("click", (e) => {
    if (!suggestionBox.contains(e.target) && e.target !== foodInput) {
      suggestionBox.style.display = "none";
    }
  });

  // Debounced input listener
  foodInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(showSuggestions, 150);
  });

  // -----------------------------
  // Load current planned meals
  // -----------------------------
  async function loadMeals() {
    try {
      const res = await fetch("/meal-planner/data");
      const data = await res.json();

      tbody.innerHTML = "";

      data.forEach((r) => {
        const kcal = Number(r.calories) || 0;

        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${r.meal_type}</td>
          <td>${r.food_name}</td>
          <td>${kcal.toFixed(1)} kcal</td>
          <td><button class="delete-btn" data-id="${r.id}">🗑</button></td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.error("❌ Failed to load meals:", err);
    }
  }

  // -----------------------------
  // Add a new planned meal (weight only)
  // -----------------------------
  addBtn.addEventListener("click", async () => {
    const name = foodInput.value.trim();
    const type = mealType.value;
    let weight = parseFloat(weightInput.value);
    const unit = unitSelect.value;

    if (!name) {
      alert("⚠ Please enter a food name.");
      return;
    }
    if (isNaN(weight) || weight <= 0) {
      alert("⚠ Please enter a valid weight > 0.");
      return;
    }

    // Convert to grams
    const weightInGrams = convertToGrams(weight, unit);

    const payload = {
      meal_type: type,
      food_name: name,
      weight: weightInGrams,
    };

    // Get CSRF token from meta tag (set by base.html)
    const csrfToken = document
      .querySelector('meta[name="csrf-token"]')
      ?.getAttribute("content");

    try {
      const res = await fetch("/meal-planner/add", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(payload),
      });

      const result = await res.json();

      if (result.status === "success") {
        // Clear form
        foodInput.value = "";
        weightInput.value = "";
        unitSelect.value = "g";
        // Reload meal list (to show new meal)
        await loadMeals();
      } else {
        alert("⚠ Failed to add meal: " + (result.error || "Unknown error"));
      }
    } catch (err) {
      console.error("❌ Failed to add meal:", err);
      alert("❌ Error adding meal. Check console for details.");
    }
  });

  // -----------------------------
  // Delete a planned meal
  // -----------------------------
  document.addEventListener("click", async (e) => {
    if (e.target.classList.contains("delete-btn")) {
      const id = e.target.getAttribute("data-id");
      if (!id) {
        alert("❌ Missing meal ID.");
        return;
      }

      if (confirm("Are you sure you want to delete this meal?")) {
        const csrfToken = document
          .querySelector('meta[name="csrf-token"]')
          ?.getAttribute("content");

        try {
          const res = await fetch(`/meal-planner/delete/${id}`, {
            method: "POST",
            headers: {
              "X-CSRFToken": csrfToken,
            },
          });
          const result = await res.json();

          if (result.status === "success") {
            // Reload the list to reflect deletion
            await loadMeals();
            console.log("✅ Meal deleted successfully!");
          } else {
            alert("⚠ Failed to delete meal. Try again.");
          }
        } catch (err) {
          console.error("❌ Delete failed:", err);
          alert("❌ Error deleting meal.");
        }
      }
    }
  });

  // -----------------------------
  // Initialize
  // -----------------------------
  await loadFoods();
  await loadMeals();
});
