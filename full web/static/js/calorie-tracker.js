// =============================
// 🔥 Calorie Tracker Logic + Auto Suggestions
// =============================

let calorieGoal = 2000;
let totalCalories = 0;
let foods = [];
let foodIndex = [];
let debounceTimer = null;

const foodInput = document.getElementById("food");
const calInput = document.getElementById("foodCalories");

// =============================
// 🧭 Progress Ring Update
// =============================
function updateProgress() {
  const percent = Math.min((totalCalories / calorieGoal) * 100, 100);
  const circle = document.querySelector(".progress-ring .progress");
  const radius = 50;
  const circumference = 2 * Math.PI * radius;

  circle.style.strokeDasharray = circumference;
  circle.style.strokeDashoffset = circumference - (percent / 100) * circumference;
  document.getElementById("progressText").innerText = `${Math.floor(percent)}%`;
  document.getElementById("calorieIntake").innerText = totalCalories.toFixed(0);
}

// =============================
// 🍎 Add Food Manually
// =============================
document.getElementById("addFood").addEventListener("click", () => {
  const name = foodInput.value.trim();
  const cal = parseFloat(calInput.value);
  if (!name || isNaN(cal)) return;

  foods.push({ name, calories: cal });
  totalCalories += cal;

  const li = document.createElement("li");
  li.textContent = `${name} - ${cal} kcal`;
  document.getElementById("foodList").appendChild(li);

  foodInput.value = "";
  calInput.value = "";

  updateProgress();
  renderMealPieChart("mealBreakdownChart", foods);
});

// =============================
// 🎯 Set Goal
// =============================
document.getElementById("setGoal").addEventListener("click", () => {
  const newGoal = parseInt(document.getElementById("dailyGoal").value);
  if (newGoal > 0) {
    calorieGoal = newGoal;
    document.getElementById("goalDisplay").innerText = calorieGoal;
    updateProgress();
  }
});

// =============================
// 🔄 Sync with Backend (meal_logs)
// =============================
async function syncWithMealLogs() {
  try {
    const res = await fetch("/meal-tracker/data");
    const data = await res.json();

    foods = data.map(r => ({
      name: r.food_name || r[1] || "Unknown",
      calories: parseFloat(r.calories || r[2] || 0)
    }));

    totalCalories = foods.reduce((sum, f) => sum + f.calories, 0);

    const list = document.getElementById("foodList");
    list.innerHTML = "";
    foods.forEach(f => {
      const li = document.createElement("li");
      li.textContent = `${f.name} - ${f.calories} kcal`;
      list.appendChild(li);
    });

    updateProgress();
    renderMealPieChart("mealBreakdownChart", foods);
    await renderWeeklyBarChart("weeklyTrendChart");
  } catch (e) {
    console.error("⚠️ Sync error:", e);
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  await syncWithMealLogs();
  await loadFoods();
});

// =============================
// 🌿 Auto-Suggestion System
// =============================
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
    console.error("❌ Could not load foods:", err);
  }
}

const suggestionBox = document.createElement("div");
suggestionBox.classList.add("suggestions-box");
foodInput.parentElement.appendChild(suggestionBox);

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

  const matches = foodIndex.filter(f => f.name.toLowerCase().includes(query)).slice(0, 8);
  if (matches.length === 0) {
    suggestionBox.style.display = "none";
    return;
  }

  matches.forEach(item => {
    const div = document.createElement("div");
    div.textContent = `${item.name} (${item.calories} kcal)`;
    div.addEventListener("click", () => selectFood(item));
    suggestionBox.appendChild(div);
  });

  suggestionBox.style.display = "block";
}

function selectFood(item) {
  foodInput.value = item.name;
  calInput.value = item.calories;
  suggestionBox.style.display = "none";
}

document.addEventListener("click", (e) => {
  if (!suggestionBox.contains(e.target) && e.target !== foodInput) {
    suggestionBox.style.display = "none";
  }
});

// =============================
// 📊 Chart Rendering Functions
// =============================
function renderMealPieChart(canvasId, foods) {
  const ctx = document.getElementById(canvasId)?.getContext("2d");
  if (!ctx) return;
  if (window.mealPieChart) window.mealPieChart.destroy();

  window.mealPieChart = new Chart(ctx, {
    type: "pie",
    data: {
      labels: foods.map(f => f.name),
      datasets: [{
        data: foods.map(f => f.calories),
        backgroundColor: [
          "#4CAF50", "#2196F3", "#FFC107", "#E91E63", "#9C27B0",
          "#FF9800", "#009688", "#FF5722", "#3F51B5", "#00BCD4"
        ],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "bottom" },
        title: { display: false }
      },
      animation: { animateScale: true, animateRotate: true }
    }
  });
}

// =============================
// 📅 Weekly Calorie Trend Chart
// =============================
async function renderWeeklyBarChart(canvasId) {
  const ctx = document.getElementById(canvasId)?.getContext("2d");
  if (!ctx) return;
  if (window.weeklyBarChart) window.weeklyBarChart.destroy();

  try {
    const res = await fetch("/meal-tracker/data?range=7");
    const data = await res.json();

    const days = data.map(d => d.date || d[0] || "Day");
    const calories = data.map(d => parseFloat(d.total || d[1] || 0));

    window.weeklyBarChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: days,
        datasets: [{
          label: "Calories (kcal)",
          data: calories,
          backgroundColor: "#2196F3",
          borderRadius: 8,
          hoverBackgroundColor: "#1976D2"
        }]
      },
      options: {
        responsive: true,
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: "Calories (kcal)" },
            ticks: { stepSize: 200 }
          },
          x: { title: { display: true, text: "Date" } }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#2196F3",
            titleColor: "#fff",
            bodyColor: "#fff",
            cornerRadius: 6
          }
        }
      }
    });
  } catch (e) {
    console.error("⚠️ Weekly chart error:", e);
  }
}
