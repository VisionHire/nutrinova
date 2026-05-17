// =============================
// 🍊 Nutrition Analyzer Logic (Auto Suggestions Fixed)
// =============================

document.addEventListener("DOMContentLoaded", async () => {
  const foodInput = document.getElementById("foodName");
  const suggestionBox = document.getElementById("analyzerSuggestionsBox"); // ✅ already in HTML
  const resultsBox = document.getElementById("nutrientResults");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const chartCanvas = document.getElementById("macroChart");

  let foodsIndex = [];
  let debounceTimer = null;

  // -----------------------------
  // Load foods.json from backend
  // -----------------------------
  async function loadFoods() {
    try {
      const res = await fetch("/foods-json", { cache: "no-store" });
      const data = await res.json();
      foodsIndex = Object.keys(data).map((key) => ({
        name: key.charAt(0).toUpperCase() + key.slice(1),
        data: data[key].macronutrients,
      }));
      console.log("✅ Loaded", foodsIndex.length, "food items");
    } catch (err) {
      console.error("❌ Failed to load foods.json:", err);
    }
  }

  // -----------------------------
  // Show suggestions
  // -----------------------------
  foodInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(showSuggestions, 150);
  });

  function showSuggestions() {
    const query = foodInput.value.trim().toLowerCase();
    suggestionBox.innerHTML = "";

    if (!query) {
      suggestionBox.style.display = "none";
      return;
    }

    const matches = foodsIndex
      .filter((item) => item.name.toLowerCase().includes(query))
      .slice(0, 8);

    if (matches.length === 0) {
      suggestionBox.style.display = "none";
      return;
    }

    matches.forEach((item) => {
      const div = document.createElement("div");
      div.textContent = `${item.name} (${item.data.calories || 0} kcal)`;
      div.addEventListener("click", () => selectFood(item));
      suggestionBox.appendChild(div);
    });

    suggestionBox.style.display = "block";
  }

  // -----------------------------
  // Select food item
  // -----------------------------
  function selectFood(item) {
    foodInput.value = item.name;
    suggestionBox.style.display = "none";
    displayNutrients(item.data);
  }

  // Hide dropdown when clicking elsewhere
  document.addEventListener("click", (e) => {
    if (!suggestionBox.contains(e.target) && e.target !== foodInput) {
      suggestionBox.style.display = "none";
    }
  });

  // -----------------------------
  // Analyze button (manual search)
  // -----------------------------
  analyzeBtn.addEventListener("click", () => {
    const query = foodInput.value.trim().toLowerCase();
    const found = foodsIndex.find((f) => f.name.toLowerCase() === query);
    if (found) {
      displayNutrients(found.data);
    } else {
      resultsBox.innerHTML = `<p>⚠️ Food not found in database.</p>`;
    }
  });

  // -----------------------------
  // Display nutrient results
  // -----------------------------
  function displayNutrients(nutrients) {
    const { calories = 0, protein = 0, carbohydrate = 0, total_fats = 0 } = nutrients;

    resultsBox.innerHTML = `
      <p><strong>Calories:</strong> ${calories} kcal</p>
      <p><strong>Protein:</strong> ${protein} g</p>
      <p><strong>Carbohydrates:</strong> ${carbohydrate} g</p>
      <p><strong>Fats:</strong> ${total_fats} g</p>
    `;

    chartCanvas.style.display = "block";
    renderMacroChart({ calories, protein, carbohydrate, total_fats });
  }

  // -----------------------------
  // Render Chart
  // -----------------------------
  function renderMacroChart({ calories, protein, carbohydrate, total_fats }) {
    if (!chartCanvas) return;
    const ctx = chartCanvas.getContext("2d");
    if (window.nutritionChart) window.nutritionChart.destroy();

    window.nutritionChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["Protein", "Carbohydrates", "Fats"],
        datasets: [
          {
            data: [protein, carbohydrate, total_fats],
            backgroundColor: ["#66BB6A", "#42A5F5", "#FFB74D"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        cutout: "70%",
        plugins: {
          legend: { position: "bottom" },
          title: { display: false },
        },
      },
    });
  }

  // -----------------------------
  // Init
  // -----------------------------
  await loadFoods();
});
