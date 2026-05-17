// =============================
// 🥗 NutriTrack Meal Tracker
// =============================

let mealChart;

// Build the request URL (with optional ?date=)
function buildTrackerUrl() {
  const date = document.getElementById("filterDate").value;
  return date
    ? `/meal-tracker/data?date=${encodeURIComponent(date)}`
    : `/meal-tracker/data`;
}

// 🔄 Load meals (today or by selected date)
async function loadMeals() {
  try {
    const res = await fetch(buildTrackerUrl());
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json(); // [{meal_type, food_name, calories}, ...]

    const tbody = document.querySelector("#mealTable tbody");
    tbody.innerHTML = "";

    let totalCalories = 0;
    const labels = [];
    const values = [];

    // 🧾 Table + chart data
    data.forEach(item => {
      const mealType = item.meal_type || "—";
      const foodName = item.food_name || "—";
      const calories = Number(item.calories || 0);

      totalCalories += calories;
      labels.push(`${mealType} (${foodName})`);
      values.push(calories);

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${mealType}</td>
        <td>${foodName}</td>
        <td>${calories.toFixed(1)} kcal</td>
      `;
      tbody.appendChild(tr);
    });

    // 🧮 Total calories
    document.getElementById("totalCalories").textContent = totalCalories.toFixed(1);

    // 📊 Update chart
    renderMealChart(labels, values);
  } catch (err) {
    console.error("Error loading meals:", err);
  }
}

// 📈 Render Chart.js Pie Chart
function renderMealChart(labels, values) {
  const ctx = document.getElementById("mealChart").getContext("2d");
  if (mealChart) mealChart.destroy();

  mealChart = new Chart(ctx, {
    type: "pie",
    data: {
      labels: labels.length ? labels : ["No Meals"],
      datasets: [{
        data: values.length ? values : [1],
        // Using default colors is fine; providing a small palette here:
        backgroundColor: [
          "#4CAF50", "#2196F3", "#FFC107", "#E91E63",
          "#FF5722", "#9C27B0", "#00BCD4", "#8BC34A"
        ],
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: {
            label: (context) => {
              const label = context.label || "";
              const val = Number(context.parsed || 0).toFixed(1);
              return `${label}: ${val} kcal`;
            }
          }
        }
      }
    }
  });
}

// 🚀 Load meals on page ready
window.addEventListener("DOMContentLoaded", loadMeals);
