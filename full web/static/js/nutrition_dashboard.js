// static/js/nutrition_dashboard.js
// NutriNova Nutrition Dashboard – Client-side enhancements

document.addEventListener("DOMContentLoaded", function () {
  // Ensure Chart.js is loaded
  if (typeof Chart === "undefined") {
    console.error("Chart.js is not loaded. The chart cannot be rendered.");
    return;
  }

  // Initialize the 7‑day chart
  initWeekChart();

  // Load today's planned meals
  loadPlannedMeals();

  // Load today's eaten foods
  loadTodayFoods();

  // (Optional) setup a refresh button if exists
  setupRefreshButton();
});

/**
 * Initializes the Chart.js line chart using data from the global `weekData` variable.
 * The global variable is set in the HTML template via:
 *   <script>window.weekData = {{ week_data|tojson }};</script>
 */
function initWeekChart() {
  const canvas = document.getElementById("weekChart");
  if (!canvas) {
    console.warn("Canvas element #weekChart not found.");
    return;
  }
  if (typeof weekData === "undefined" || !Array.isArray(weekData)) {
    console.warn("weekData is not defined or not an array.");
    return;
  }

  const ctx = canvas.getContext("2d");
  // Format dates to "MM/DD" (or "DD/MM" – change as needed)
  const formattedDates = weekData.map((day) => {
    const d = new Date(day.date);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });

  new Chart(ctx, {
    type: "line",
    data: {
      labels: formattedDates,
      datasets: [
        {
          label: "Calories",
          data: weekData.map((day) => day.calories),
          borderColor: "rgba(46, 204, 113, 1)",
          backgroundColor: "rgba(46, 204, 113, 0.1)",
          tension: 0.1,
          yAxisID: "y",
        },
        {
          label: "Protein (g)",
          data: weekData.map((day) => day.protein),
          borderColor: "rgba(52, 152, 219, 1)",
          backgroundColor: "rgba(52, 152, 219, 0.1)",
          tension: 0.1,
          yAxisID: "y1",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          ticks: {
            maxRotation: 45,
            minRotation: 45,
            autoSkip: true,
            maxTicksLimit: 7,
          },
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: "Calories" },
        },
        y1: {
          position: "right",
          beginAtZero: true,
          title: { display: true, text: "Protein (g)" },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

/**
 * Load planned meals for today and display them with accept/deny buttons.
 */
function loadPlannedMeals() {
  fetch("/nutrition/planned-meals")
    .then((response) => response.json())
    .then((meals) => {
      const container = document.getElementById("planned-meals-list");
      if (!container) return;

      if (!meals.length) {
        container.innerHTML =
          '<div class="empty-message">No planned meals for today</div>';
        return;
      }

      let html = "";
      meals.forEach((meal) => {
        html += `
          <div class="planned-item" data-id="${meal.id}">
            <div class="planned-info">
              <span class="meal-type">${meal.meal_type}</span>
              <strong>${meal.food_name}</strong>
              <span class="badge">${meal.weight}g</span>
              <span>${Math.round(meal.calories)} kcal</span>
            </div>
            <div class="planned-actions">
              <button class="btn-accept" data-id="${meal.id}">✓ Eat</button>
              <button class="btn-deny" data-id="${meal.id}">✗ Deny</button>
            </div>
          </div>
        `;
      });
      container.innerHTML = html;

      // Attach event listeners for accept/deny
      document.querySelectorAll(".btn-accept").forEach((btn) => {
        btn.addEventListener("click", () => acceptMeal(btn.dataset.id));
      });
      document.querySelectorAll(".btn-deny").forEach((btn) => {
        btn.addEventListener("click", () => denyMeal(btn.dataset.id));
      });
    })
    .catch((err) => console.error("Error loading planned meals:", err));
}

/**
 * Load today's eaten foods and display them with delete buttons.
 */
function loadTodayFoods() {
  fetch("/nutrition/today-foods")
    .then((response) => response.json())
    .then((foods) => {
      const container = document.getElementById("today-foods-list");
      if (!container) return;

      if (!foods.length) {
        container.innerHTML =
          '<div class="empty-message">No foods eaten today yet.</div>';
        return;
      }

      let html = "";
      foods.forEach((f) => {
        html += `
          <div class="food-item" data-id="${f.id}">
            <div class="food-info">
              <span class="meal-type">${f.meal_type}</span>
              <strong>${f.food_name}</strong>
              <span class="badge">${f.weight}g</span>
              <span>${f.calories ? f.calories.toFixed(0) : 0} kcal</span>
              <span>P:${f.protein ? f.protein.toFixed(1) : 0}g</span>
              <span>C:${f.carbs ? f.carbs.toFixed(1) : 0}g</span>
              <span>F:${f.fats ? f.fats.toFixed(1) : 0}g</span>
            </div>
            <div class="food-actions">
              <button class="btn-delete" data-id="${f.id}">Delete</button>
            </div>
          </div>
        `;
      });
      container.innerHTML = html;

      // Attach delete event listeners
      document.querySelectorAll(".btn-delete").forEach((btn) => {
        btn.addEventListener("click", () => deleteFood(btn.dataset.id));
      });
    })
    .catch((err) => console.error("Error loading today's foods:", err));
}

/**
 * Accept a planned meal: send POST request, then reload the page.
 */
function acceptMeal(planId) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  fetch(`/nutrition/accept-meal/${planId}`, {
    method: "POST",
    headers: {
      "X-CSRFToken": csrfToken,
    },
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.status === "success") {
        location.reload(); // Refresh to show updated progress
      } else {
        alert("Error accepting meal: " + (data.error || "Unknown error"));
      }
    })
    .catch((err) => {
      console.error("Accept meal error:", err);
      alert("Failed to accept meal. Check console.");
    });
}

/**
 * Deny a planned meal: send POST request, then reload the page.
 */
function denyMeal(planId) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  fetch(`/nutrition/deny-meal/${planId}`, {
    method: "POST",
    headers: {
      "X-CSRFToken": csrfToken,
    },
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.status === "success") {
        location.reload();
      } else {
        alert("Error denying meal: " + (data.error || "Unknown error"));
      }
    })
    .catch((err) => {
      console.error("Deny meal error:", err);
      alert("Failed to deny meal. Check console.");
    });
}

/**
 * Delete an eaten food: send DELETE request, then reload the page.
 */
function deleteFood(logId) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  fetch(`/nutrition/delete-food/${logId}`, {
    method: "DELETE",
    headers: {
      "X-CSRFToken": csrfToken,
    },
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.status === "success") {
        location.reload();
      } else {
        alert("Error deleting food: " + (data.error || "Unknown error"));
      }
    })
    .catch((err) => {
      console.error("Delete error:", err);
      alert("Failed to delete food. Check console.");
    });
}

/**
 * Optional: Refresh dashboard data via API and update progress bars dynamically.
 * (Not used in current workflow because we reload the page after actions.)
 */
function refreshDashboard() {
  fetch("/nutrition/api/dashboard")
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      // Update progress bars
      updateProgressBar(
        "calories",
        data.today_intake.total_calories,
        data.targets.calories,
      );
      updateProgressBar(
        "protein",
        data.today_intake.total_protein,
        data.targets.protein_grams,
      );
      updateProgressBar(
        "carbs",
        data.today_intake.total_carbs,
        data.targets.carbs_grams,
      );
      updateProgressBar(
        "fats",
        data.today_intake.total_fat,
        data.targets.fat_grams,
      );

      // Update improvement bar
      const improvementEl = document.querySelector(".improvement-bar-fill");
      if (improvementEl) {
        const improvement = data.improvement;
        improvementEl.style.width = Math.min(improvement + 100, 100) + "%";
        improvementEl.style.backgroundColor =
          improvement >= 0 ? "#27ae60" : "#e67e22";
        improvementEl.innerText =
          (improvement > 0 ? "+" : "") + improvement + "%";
      }

      // Update suggestions
      const suggestionsDiv = document.querySelector(".suggestions");
      if (suggestionsDiv) {
        if (data.suggestions.length) {
          let html = "<ul>";
          data.suggestions.forEach((s) => {
            html += `<li>${s}</li>`;
          });
          html += "</ul>";
          suggestionsDiv.innerHTML = html;
        } else {
          suggestionsDiv.innerHTML =
            "<p>Great job! You're on track to meet all your daily targets.</p>";
        }
      }

      console.log("Dashboard data refreshed", data);
    })
    .catch((err) => console.error("Error refreshing dashboard:", err));
}

/**
 * Helper to update a single progress bar and its text.
 * Assumes HTML elements have IDs like "progress-calories" and a sibling .progress-value.
 */
function updateProgressBar(nutrient, consumed, target) {
  const bar = document.getElementById(`progress-${nutrient}`);
  if (!bar) return;

  const valueEl = bar
    .closest(".progress-item")
    ?.querySelector(".progress-value");
  if (!valueEl) return;

  const percent = target > 0 ? Math.min((consumed / target) * 100, 100) : 0;
  bar.style.width = percent + "%";

  // Choose appropriate unit
  const unit = nutrient === "calories" ? "kcal" : "g";
  valueEl.innerText = `${Number(consumed).toFixed(1)} / ${target} ${unit}`;
}

/**
 * Setup a refresh button if present in the HTML.
 */
function setupRefreshButton() {
  const btn = document.getElementById("refresh-dashboard-btn");
  if (btn) {
    btn.addEventListener("click", refreshDashboard);
  }
}
