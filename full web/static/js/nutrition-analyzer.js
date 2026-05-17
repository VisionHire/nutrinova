// =============================
// 🍊 Nutrition Analyzer — Full Functional Version (Smaller Donut)
// =============================

document.addEventListener("DOMContentLoaded", async () => {
  const foodInput = document.getElementById("foodName");
  const suggestionBox = document.getElementById("analyzerSuggestionsBox");
  const resultsBox = document.getElementById("nutrientResults");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const chartCanvas = document.getElementById("macroChart");
  const categorySelect = document.getElementById("categorySelect");

  let foodsIndex = [];
  let debounceTimer = null;

  // -----------------------------
  // Load foods.json
  // -----------------------------
  async function loadFoods() {
    try {
      const res = await fetch("/foods-json", { cache: "no-store" });
      const data = await res.json();

      foodsIndex = Object.entries(data).map(([key, value]) => ({
        name: key.charAt(0).toUpperCase() + key.slice(1),
        data: value
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
      .filter((f) => f.name.toLowerCase().includes(query))
      .slice(0, 8);

    if (matches.length === 0) {
      suggestionBox.style.display = "none";
      return;
    }

    matches.forEach((item) => {
      const div = document.createElement("div");
      const kcal = item.data.macronutrients?.calories || 0;
      div.textContent = `${item.name} (${kcal} kcal)`;
      div.addEventListener("click", () => selectFood(item));
      suggestionBox.appendChild(div);
    });

    suggestionBox.style.display = "block";
  }

  // -----------------------------
  // Select food from suggestion
  // -----------------------------
  function selectFood(item) {
    foodInput.value = item.name;
    suggestionBox.style.display = "none";
    analyzeFood(item);
  }

  // Hide dropdown when clicked elsewhere
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
      analyzeFood(found);
    } else {
      resultsBox.innerHTML = `<p>⚠️ Food not found in database.</p>`;
      chartCanvas.style.display = "none";
    }
  });

  // -----------------------------
  // Analyze food by category
  // -----------------------------
  function analyzeFood(food) {
    const selectedCategory = categorySelect.value;
    const data = food.data[selectedCategory];

    if (!data) {
      resultsBox.innerHTML = `<p>⚠️ No data available for this category.</p>`;
      chartCanvas.style.display = "none";
      return;
    }

    displayNutrients(selectedCategory, data);
  }

  // -----------------------------
  // Display Nutrients by Category
  // -----------------------------
  function displayNutrients(category, nutrients) {
    chartCanvas.style.display = "none";
    let html = "<h3>🔍 Nutrient Breakdown</h3>";

    if (category === "macronutrients") {
      const {
        calories = 0, protein = 0, carbohydrate = 0, total_fats = 0,
        saturated_fats = 0, omega_3 = 0, omega_6 = 0, fiber = 0, water = 0
      } = nutrients;

      html += `
        <p><b>Calories:</b> ${calories} kcal</p>
        <p><b>Protein:</b> ${protein} g</p>
        <p><b>Carbohydrates:</b> ${carbohydrate} g</p>
        <p><b>Total Fats:</b> ${total_fats} g</p>
        <p><b>Saturated Fats:</b> ${saturated_fats} g</p>
        <p><b>Omega-3:</b> ${omega_3} g</p>
        <p><b>Omega-6:</b> ${omega_6} g</p>
        <p><b>Fiber:</b> ${fiber} g</p>
        <p><b>Water:</b> ${water} g</p>
      `;

      chartCanvas.style.display = "block";
      renderMacroChart({ protein, carbohydrate, total_fats, saturated_fats, omega_3, omega_6, fiber, water });

    } else if (category === "vitamins") {
      const v = nutrients;
      html += `
  <p><b>Vitamin A:</b> ${v["vitamin_a"] ?? "0"} µg</p>
  <p><b>Vitamin B1 (Thiamine):</b> ${v["vitamin_b1"] ?? "0"} mg</p>
  <p><b>Vitamin B2 (Riboflavin):</b> ${v["vitamin_b2"] ?? "0"} mg</p>
  <p><b>Vitamin B3 (Niacin):</b> ${v["vitamin_b3"] ?? "0"} mg</p>
  <p><b>Vitamin B5 (Pantothenic Acid):</b> ${v["vitamin_b5"] ?? "0"} mg</p>
  <p><b>Vitamin B6:</b> ${v["vitamin_b6"] ?? "0"} mg</p>
  <p><b>Vitamin B7 (Biotin):</b> ${v["vitamin_b7"] ?? "0"} µg</p>
  <p><b>Vitamin B9 (Folate):</b> ${v["vitamin_b9"] ?? "0"} µg</p>
  <p><b>Vitamin B12:</b> ${v["vitamin_b12"] ?? "0"} µg</p>
  <hr>
  <p><b>Vitamin C:</b> ${v["vitamin_c"] ?? "0"} mg</p>
  <p><b>Vitamin D:</b> ${v["vitamin_d"] ?? "0"} µg</p>
  <p><b>Vitamin E:</b> ${v["vitamin_e"] ?? "0"} mg</p>
  <p><b>Vitamin K:</b> ${v["vitamin_k"] ?? "0"} µg</p>
  <p><b>Choline:</b> ${v["choline"] ?? "0"} mg</p>
`;


    } else if (category === "minerals_and_trace") {
      const m = nutrients;
      html += `
  <p><b>Calcium:</b> ${m.calcium || 0} mg</p>
  <p><b>Iron:</b> ${m.iron || 0} mg</p>
  <p><b>Magnesium:</b> ${m.magnesium || 0} mg</p>
  <p><b>Phosphorus:</b> ${m.phosphorus || 0} mg</p>
  <p><b>Potassium:</b> ${m.potassium || 0} mg</p>
  <p><b>Sodium:</b> ${m.sodium || 0} mg</p>
  <p><b>Zinc:</b> ${m.zinc || 0} mg</p>
  <p><b>Iodine:</b> ${m.iodine || 0} µg</p>
  <p><b>Selenium:</b> ${m.selenium || 0} µg</p>
  <p><b>Copper:</b> ${m.copper || 0} mg</p>
  <p><b>Manganese:</b> ${m.manganese || 0} mg</p>
  <p><b>Chromium:</b> ${m.chromium || 0} µg</p>
  <p><b>Molybdenum:</b> ${m.molybdenum || 0} µg</p>
  <p><b>Fluoride:</b> ${m.fluoride || 0} mg</p>
`;

    }

    resultsBox.innerHTML = html;
  }

  // -----------------------------
  // Render Macro Chart (Smaller Donut)
  // -----------------------------
  function renderMacroChart({ calories, protein, carbohydrate, total_fats, saturated_fats, omega_3, omega_6, fiber, water }) {
    const ctx = chartCanvas.getContext("2d");
    if (window.nutritionChart) window.nutritionChart.destroy();

    // ✅ Make chart smaller
    chartCanvas.width = 220;
    chartCanvas.height = 220;

    window.nutritionChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["Calorie", "Protein", "Carbohydrates", "Fats", "Saturated Fats", "Omega-3", "Omega-6", "Fiber", "Water"],
        datasets: [
          {
            data: [calories, protein, carbohydrate, total_fats, saturated_fats, omega_3, omega_6, fiber, water],
            backgroundColor: ["#ff79a7", "#c9c92dff", "#d2f4e1", "#fdf5c9", "#ea8a9d", "#823dd1", "#ffb35c", "#cca995", "#14bae8ff"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: "80%", // smaller, more elegant ring
        plugins: {
          legend: { position: "bottom" },
          title: { display: true },
        },
      },
    });
  }

  // -----------------------------
  // Init
  // -----------------------------
  await loadFoods();
});
