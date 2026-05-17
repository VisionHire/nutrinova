// ==============================
// 🌿 Load Foods & Setup Suggestions
// ==============================
let foodsData = {};

async function loadFoods() {
  try {
    const res = await fetch("/api/foods");
    foodsData = await res.json();
    console.log("✅ Loaded foods:", Object.keys(foodsData).length);

    // Setup custom suggestions
    setupCustomSuggestions("meal", "calories", "mealSuggestionsBox");
    setupCustomSuggestions("food", "foodCalories", "foodSuggestionsBox");
    setupCustomSuggestions("foodName", null, "analyzerSuggestionsBox");
  } catch (err) {
    console.error("❌ Error loading foods:", err);
  }
}

window.addEventListener("DOMContentLoaded", loadFoods);

// ==============================
// ⚡ Custom Suggestion System
// ==============================
function setupCustomSuggestions(inputId, calInputId, boxId) {
  const input = document.getElementById(inputId);
  const box = document.getElementById(boxId);
  const calInput = calInputId ? document.getElementById(calInputId) : null;
  if (!input || !box) return;

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    box.innerHTML = "";
    if (!query) return (box.style.display = "none");

    const matches = Object.keys(foodsData).filter(name => name.includes(query)).slice(0, 6);
    if (!matches.length) {
      box.style.display = "none";
      return;
    }

    matches.forEach(name => {
      const item = document.createElement("div");
      item.classList.add("suggestion-item");
      item.textContent = name;

      item.addEventListener("click", () => {
        input.value = name;
        box.style.display = "none";

        if (calInput && foodsData[name]) {
          calInput.value = foodsData[name].macronutrients.calories || 0;
        }
      });

      box.appendChild(item);
    });

    box.style.display = "block";
  });

  document.addEventListener("click", e => {
    if (!box.contains(e.target) && e.target !== input) {
      box.style.display = "none";
    }
  });
}

// ==============================
// 🥗 Meal Planner
// ==============================
const mealList = document.getElementById("mealList");
const totalCaloriesDisplay = document.getElementById("totalCalories");
let totalCalories = 0;

document.getElementById("addMeal")?.addEventListener("click", () => {
  const mealName = document.getElementById("meal").value.trim();
  const mealCal = parseFloat(document.getElementById("calories").value) || 0;
  if (!mealName) return alert("Enter a meal name!");

  const li = document.createElement("li");
  li.innerHTML = `
    ${mealName} - ${mealCal} kcal
    <button class="remove-btn">✖️</button>
  `;

  li.querySelector(".remove-btn").addEventListener("click", () => {
    li.remove();
    totalCalories -= mealCal;
    totalCaloriesDisplay.textContent = totalCalories;
  });

  mealList.appendChild(li);
  totalCalories += mealCal;
  totalCaloriesDisplay.textContent = totalCalories;

  document.getElementById("meal").value = "";
  document.getElementById("calories").value = "";
});

// ==============================
// 🔥 Calorie Tracker
// ==============================
const foodList = document.getElementById("foodList");
const calorieIntakeDisplay = document.getElementById("calorieIntake");
let calorieIntake = 0;

document.getElementById("addFood")?.addEventListener("click", () => {
  const foodName = document.getElementById("food").value.trim();
  const foodCal = parseFloat(document.getElementById("foodCalories").value) || 0;
  if (!foodName) return alert("Enter a food name!");

  const li = document.createElement("li");
  li.innerHTML = `
    ${foodName} - ${foodCal} kcal
    <button class="remove-btn">✖️</button>
  `;

  li.querySelector(".remove-btn").addEventListener("click", () => {
    li.remove();
    calorieIntake -= foodCal;
    calorieIntakeDisplay.textContent = calorieIntake;
  });

  foodList.appendChild(li);
  calorieIntake += foodCal;
  calorieIntakeDisplay.textContent = calorieIntake;

  document.getElementById("food").value = "";
  document.getElementById("foodCalories").value = "";
});

// ==============================
// 🍎 Nutrition Analyzer (unchanged)
// ==============================
document.getElementById("analyzeBtn")?.addEventListener("click", () => {
  const foodName = document.getElementById("foodName").value.trim().toLowerCase();
  const category = document.getElementById("categorySelect").value;
  const resultsDiv = document.getElementById("nutrientResults");
  const chartCanvas = document.getElementById("macroChart");

  if (!foodName || !foodsData[foodName]) {
    resultsDiv.innerHTML = `<p style="color:red;">Food not found. Try another!</p>`;
    chartCanvas.style.display = "none";
    return;
  }

  const data = foodsData[foodName][category];
  resultsDiv.innerHTML = `
    <h4>${foodName.charAt(0).toUpperCase() + foodName.slice(1)} — ${category}</h4>
    <ul>${Object.entries(data)
      .map(([k, v]) => `<li><strong>${k.replace(/_/g, " ")}:</strong> ${v}</li>`)
      .join("")}</ul>
  `;

  if (category === "macronutrients") {
    const ctx = chartCanvas.getContext("2d");
    chartCanvas.style.display = "block";
    if (window.macroChart) window.macroChart.destroy();
    window.macroChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["Protein", "Carbohydrates", "Fats"],
        datasets: [{
          data: [data.protein || 0, data.carbohydrate || 0, data.total_fats || 0],
          backgroundColor: ["#4CAF50", "#FFC107", "#FF5722"]
        }]
      }
    });
  } else {
    chartCanvas.style.display = "none";
  }
});
