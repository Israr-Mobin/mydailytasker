// ========================= THEME MANAGEMENT =========================
function setTheme(theme) {
    document.body.className = theme;
    document.documentElement.className = theme;
    localStorage.setItem('theme', theme);
    
    // Save to database 
    fetch('/update-theme', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: 'theme=' + encodeURIComponent(theme)
    }).then(response => response.json())
      .then(data => {
          if (data.success) {
              console.log('Theme saved to database!');
          }
      })
      .catch(error => {
          console.error('Failed to save theme:', error);
      });
    
    // Update active state
    document.querySelectorAll('.theme-option').forEach(opt => {
        opt.classList.remove('active');
        if (opt.dataset.theme === theme) {
            opt.classList.add('active');
        }
    });
}

// Applying these IMMEDIATELY before page renders (prevents flash)
(function() {
    const savedTheme = localStorage.getItem('theme') || 'theme-light';
    document.documentElement.className = savedTheme;
})();

// ========================= MENU & MODAL MANAGEMENT =========================
function toggleMenu() {
    // Reset menu to main view when opening
    const menu = document.getElementById('mainMenu');
    
    if (!menu.classList.contains('active')) {
        // Opening menu - reset to main view
        showMenuView('mainMenuView');
    }
    
    menu.classList.toggle('active');
}

function toggleAddMenu() {
    const menu = document.getElementById('addMenu');
    menu.classList.toggle('active');
}

// ========================= SUBMENU FUNCTIONALITY =========================
// Show a specific menu view (replaces current view)
function showMenuView(viewId) {
    // Hide all menu views
    document.querySelectorAll('.menu-view').forEach(view => {
        view.style.display = 'none';
    });
    
    // Show the requested view
    const targetView = document.getElementById(viewId);
    if (targetView) {
        targetView.style.display = 'block';
    }
}

// Close menu when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.top-bar-right')) {
        const menu = document.getElementById('mainMenu');
        if (menu && menu.classList.contains('active')) {
            menu.classList.remove('active');
            // Reset to main view
            showMenuView('mainMenuView');
        }
    }
});

function openModal(modalId) {
    closeAllModals();
    document.getElementById('modalOverlay').classList.add('active');
    document.getElementById(modalId).style.display = 'block';
}

function openThemeModal() { openModal('themeModal'); }
function openSettingsModal() { openModal('settingsModal'); }
function openExportModal() { openModal('exportModal'); }
function openStatsModal() { openModal('statsModal'); }
function openAddCategoryModal() { openModal('addCategoryModal'); }
function openAddTaskModal() { openModal('addTaskModal'); }
function openShareModal() { openModal('shareModal'); }

function closeAllModals() {
    document.getElementById('modalOverlay').classList.remove('active');
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
    document.getElementById('mainMenu').classList.remove('active');
    document.getElementById('addMenu').classList.remove('active');
    
    // Reset menu to main view
    showMenuView('mainMenuView');
}

// ========================= EXPORT PDF =========================
function exportPDF(type) {
    const form = document.getElementById('exportForm');
    const formData = new FormData(form);
    const categoryIds = formData.getAll('category_ids');
    
    // Get the base URLs from data attributes on the body
    const weekUrl = document.body.dataset.weekUrl || '';
    const monthUrl = document.body.dataset.monthUrl || '';
    const yearUrl = document.body.dataset.yearUrl || '';
    
    let url = '';
    if (type === 'weekly') {
        url = weekUrl;
    } else if (type === 'monthly') {
        url = monthUrl;
    } else if (type === 'yearly') {
        url = yearUrl;
    }
    
    // Add category IDs to URL
    if (categoryIds.length > 0) {
        const params = new URLSearchParams();
        categoryIds.forEach(id => params.append('category_ids', id));
        url += (url.includes('?') ? '&' : '?') + params.toString();
    }
    
    window.location.href = url;
    closeAllModals();
}

// ========================= SHARE PDF =========================
function createShareLink(pdfType) {
    const expiresIn = document.getElementById('shareExpires').value;
    
    // Navigate to create share link endpoint
    window.location.href = `/share/pdf/${pdfType}?expires=${expiresIn}`;
}

// ========================= DELETE CATEGORY =========================
function deleteCategory(categoryId, categoryName) {
    event.preventDefault();
    event.stopPropagation();
    
    if (confirm(`Delete category "${categoryName}" and ALL its tasks?\n\nThis action cannot be undone!`)) {
        document.getElementById("delete-category-id").value = categoryId;
        document.getElementById("delete-category-form").submit();
    }
}

// ========================= RECENTLY DELETED MODAL =========================
function openInactiveTasksModal() {
    openModal('inactiveTasksModal');
    loadInactiveTasks();
}

// Load inactive tasks from server
function loadInactiveTasks() {
    const loading = document.getElementById('inactiveTasksLoading');
    const empty = document.getElementById('inactiveTasksEmpty');
    const list = document.getElementById('inactiveTasksList');
    
    // Show loading
    loading.style.display = 'block';
    empty.style.display = 'none';
    list.style.display = 'none';
    
    // Fetch deleted tasks
    fetch('/tasks/deleted')
        .then(response => response.json())
        .then(tasks => {
            loading.style.display = 'none';
            
            if (tasks.length === 0) {
                empty.style.display = 'block';
            } else {
                list.style.display = 'block';
                renderInactiveTasks(tasks);
            }
        })
        .catch(error => {
            console.error('Error loading inactive tasks:', error);
            loading.style.display = 'none';
            empty.style.display = 'block';
        });
}

// Render inactive tasks in the modal
function renderInactiveTasks(tasks) {
    const list = document.getElementById('inactiveTasksList');
    list.innerHTML = '';
    
    tasks.forEach(task => {
        const taskDiv = document.createElement('div');
        taskDiv.style.cssText = 'background: var(--bg-color); padding: 12px; border-radius: 8px; margin-bottom: 8px; border: 1px solid var(--border-color);';
        
        const daysColor = task.days_until_permanent <= 2 ? '#e74c3c' : '#666';
        
        taskDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                <div style="flex: 1;">
                    <strong style="font-size: 14px;">${escapeHtml(task.title)}</strong>
                    <div style="font-size: 12px; color: #666; margin-top: 4px;">
                        📁 ${escapeHtml(task.category)} · 📅 Deleted ${task.deleted_at}
                    </div>
                </div>
            </div>
            <div style="font-size: 12px; color: ${daysColor}; margin-bottom: 8px;">
                ⏰ ${task.days_until_permanent} day${task.days_until_permanent !== 1 ? 's' : ''} until permanent deletion
            </div>
            <div style="display: flex; gap: 8px;">
                <button onclick="reactivateTask(${task.id}, '${escapeHtml(task.title)}')" 
                        class="btn" 
                        style="flex: 1; padding: 8px; font-size: 13px;">
                    🔄 Reactivate
                </button>
            </div>
        `;
        
        list.appendChild(taskDiv);
    });
}

// Reactivate a task
function reactivateTask(taskId, taskTitle) {
    if (!confirm(`Reactivate task "${taskTitle}"?\n\nIt will appear in your daily list starting today.`)) {
        return;
    }
    
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/task/restore';
    
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'task_id';
    input.value = taskId;
    
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
}

// Helper to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ========================= DELETE TASK FUNCTION (GLOBAL SCOPE) =========================
function deactivateTask(taskId) {
    console.log('Deactivating task:', taskId);
    
    // Get the current selected date from the page
    const selectedDateInput = document.querySelector('input[name="selected_date"]');
    const selectedDate = selectedDateInput ? selectedDateInput.value : new Date().toISOString().split('T')[0];
    
    console.log('Selected date:', selectedDate);
    
    // Create and submit form
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/task/delete-from-date';  
    
    const taskInput = document.createElement('input');
    taskInput.type = 'hidden';
    taskInput.name = 'task_id';
    taskInput.value = taskId;
    form.appendChild(taskInput);
    
    const dateInput = document.createElement('input');
    dateInput.type = 'hidden';
    dateInput.name = 'date';
    dateInput.value = selectedDate;
    form.appendChild(dateInput);
    
    document.body.appendChild(form);
    form.submit();
}

// ========================= PROFILE MODAL =========================
function openProfileModal() { 
    openModal('profileModal'); 
}

// ========================= HISTORY MODAL =========================
// Open history modal
function openHistoryModal() {
    openModal('historyModal');
    // Set default date to yesterday
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    document.getElementById('historyDatePicker').value = yesterday.toISOString().split('T')[0];
}

// Load history for a specific date
function loadHistoryDate(dateStr) {
    if (!dateStr) return;
    
    const loading = document.getElementById('historyLoading');
    const content = document.getElementById('historyContent');
    const empty = document.getElementById('historyEmpty');
    
    // Show loading
    loading.style.display = 'block';
    content.style.display = 'none';
    empty.style.display = 'none';
    
    // Fetch history data
    fetch(`/history/${dateStr}`)
        .then(response => response.json())
        .then(data => {
            loading.style.display = 'none';
            
            if (Object.keys(data.tasks_by_category).length === 0) {
                empty.style.display = 'block';
            } else {
                content.style.display = 'block';
                renderHistoryTasks(data);
            }
        })
        .catch(error => {
            console.error('Error loading history:', error);
            loading.style.display = 'none';
            empty.style.display = 'block';
        });
}

// Render tasks for a historical date
function renderHistoryTasks(data) {
    const display = document.getElementById('historyDateDisplay');
    const list = document.getElementById('historyTasksList');
    
    display.textContent = data.date_display;
    list.innerHTML = '';
    
    // Store current date for saving changes
    list.dataset.currentDate = data.date;
    
    // Render tasks by category
    for (const [categoryName, tasks] of Object.entries(data.tasks_by_category)) {
        const categoryDiv = document.createElement('div');
        categoryDiv.style.cssText = 'margin-bottom: 20px;';
        
        categoryDiv.innerHTML = `
            <h4 style="font-size: 14px; margin-bottom: 12px; color: var(--text-color);">${escapeHtml(categoryName)}</h4>
        `;
        
        tasks.forEach(task => {
            const taskDiv = document.createElement('div');
            taskDiv.style.cssText = 'background: var(--bg-color); padding: 12px; border-radius: 8px; margin-bottom: 8px; border: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;';
            
            taskDiv.innerHTML = `
                <label style="flex: 1; display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" 
                           data-daily-task-id="${task.id}"
                           ${task.completed ? 'checked' : ''}
                           style="margin-right: 10px;">
                    <span style="font-size: 14px;">
                        ${escapeHtml(task.title)} 
                        ${task.duration ? `<span style="color: #666; font-size: 12px;">(${escapeHtml(task.duration)})</span>` : ''}
                    </span>
                </label>
                ${task.task_id ? `
                    <button onclick="deleteTaskFromDate(${task.task_id}, '${data.date}', '${escapeHtml(task.title)}')" 
                            class="btn btn-secondary" 
                            style="padding: 6px 12px; font-size: 12px; background: #e74c3c; color: white;">
                        🗑️ Remove
                    </button>
                ` : ''}
            `;
            
            categoryDiv.appendChild(taskDiv);
        });
        
        list.appendChild(categoryDiv);
    }
}

// Save changes to historical tasks
function saveHistoryChanges() {
    const list = document.getElementById('historyTasksList');
    const dateStr = list.dataset.currentDate;
    
    if (!dateStr) {
        alert('No date selected');
        return;
    }
    
    // Get checked task IDs
    const checkboxes = list.querySelectorAll('input[type="checkbox"]');
    const completedIds = Array.from(checkboxes)
        .filter(cb => cb.checked)
        .map(cb => cb.dataset.dailyTaskId);
    
    // Submit form
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/update-daily-tasks';
    
    const dateInput = document.createElement('input');
    dateInput.type = 'hidden';
    dateInput.name = 'selected_date';
    dateInput.value = dateStr;
    form.appendChild(dateInput);
    
    const actionInput = document.createElement('input');
    actionInput.type = 'hidden';
    actionInput.name = 'action';
    actionInput.value = 'save';
    form.appendChild(actionInput);
    
    completedIds.forEach(id => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'completed_tasks';
        input.value = id;
        form.appendChild(input);
    });
    
    document.body.appendChild(form);
    form.submit();
}

function deleteTaskFromDate(taskId, dateStr, taskTitle) {
    if (!confirm(`Remove "${taskTitle}" from this date only?`)) {
        return;
    }
    
    closeAllModals();
    
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/history/delete-task-from-date';
    
    const taskInput = document.createElement('input');
    taskInput.type = 'hidden';
    taskInput.name = 'task_id';
    taskInput.value = taskId;
    form.appendChild(taskInput);
    
    const dateInput = document.createElement('input');
    dateInput.type = 'hidden';
    dateInput.name = 'date';
    dateInput.value = dateStr;
    form.appendChild(dateInput);
    
    document.body.appendChild(form);
    form.submit();
}

// Clear history selection
function clearHistorySelection() {
    document.getElementById('historyContent').style.display = 'none';
    document.getElementById('historyDatePicker').value = '';
}

// ========================= TUTORIAL SYSTEM =========================
let currentTutorialStep = 1;
const totalTutorialSteps = 4;

function showTutorial() {
    currentTutorialStep = 1;
    updateTutorialStep();
    openModal('tutorialModal');
}

function nextTutorialStep() {
    if (currentTutorialStep < totalTutorialSteps) {
        currentTutorialStep++;
        updateTutorialStep();
    } else {
        closeTutorial();
    }
}

function skipTutorial() {
    if (document.getElementById('dontShowTutorial').checked) {
        localStorage.setItem('tutorialCompleted', 'true');
    }
    closeTutorial();
}

function closeTutorial() {
    if (document.getElementById('dontShowTutorial').checked) {
        localStorage.setItem('tutorialCompleted', 'true');
    }
    closeAllModals();
}

function updateTutorialStep() {
    // Hide all steps
    document.querySelectorAll('.tutorial-step').forEach(step => {
        step.style.display = 'none';
    });
    
    // Show current step
    const currentStep = document.querySelector(`.tutorial-step[data-step="${currentTutorialStep}"]`);
    if (currentStep) {
        currentStep.style.display = 'block';
    }
    
    // Update button text
    const nextBtn = document.getElementById('tutorialNextBtn');
    if (currentTutorialStep === totalTutorialSteps) {
        nextBtn.textContent = 'Got it!';
    } else {
        nextBtn.textContent = 'Next';
    }
}

// ========================= INITIALIZATION =========================
document.addEventListener("DOMContentLoaded", function() {
    // Load saved theme on page load 
    const savedTheme = localStorage.getItem('theme') || 'theme-light';
    document.body.className = savedTheme;
    
    // Set active theme option
    document.querySelectorAll('.theme-option').forEach(opt => {
        if (opt.dataset.theme === savedTheme) {
            opt.classList.add('active');
        }
    });

    // Disable autocomplete on all input fields
    document.querySelectorAll('input').forEach(input => {
        input.setAttribute('autocomplete', 'off');
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.top-bar-right')) {
            const menu = document.getElementById('mainMenu');
            if (menu && menu.classList.contains('active')) {
                menu.classList.remove('active');
                showMenuView('mainMenuView');
            }
        }
    });

    // ========================= DELETE TASK HANDLERS =========================
    const LONG_PRESS_TIME = 600;
    let pressTimer = null;

    document.querySelectorAll('.task-item').forEach(item => {
        const taskId = item.dataset.taskId;
        
        console.log('Setting up delete handler for task:', taskId);
        
        // Check if task still exists (not deleted)
        if (!taskId || taskId === '') {
            console.log('Skipping historical task (no task_id)');
            return;
        }

        // Desktop right-click
        item.addEventListener("contextmenu", function(e) {
            e.preventDefault();
            console.log('Right-click detected on task:', taskId);
            
            // Check if viewing today or past date
            const selectedDateInput = document.querySelector('input[name="selected_date"]');
            const selectedDate = selectedDateInput ? selectedDateInput.value : new Date().toISOString().split('T')[0];
            const today = new Date().toISOString().split('T')[0];
            
            let confirmMessage;
            if (selectedDate >= today) {
                // Deleting from today/future
                confirmMessage = "Remove this task?\n\nIt will be moved to Recently Deleted and can be restored from the menu.";
            } else {
                // Deleting from past date
                const dateObj = new Date(selectedDate);
                const dateStr = dateObj.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
                confirmMessage = `Remove this task from ${dateStr} onward?\n\nIt will disappear from this date forward but remain visible on earlier dates.`;
            }
            
            if (confirm(confirmMessage)) {
                deactivateTask(taskId);
            }
        });

        // Mobile long-press
        const startPress = (e) => {
            console.log('Press started on task:', taskId);
            pressTimer = setTimeout(() => {
                // Same logic as right-click
                const selectedDateInput = document.querySelector('input[name="selected_date"]');
                const selectedDate = selectedDateInput ? selectedDateInput.value : new Date().toISOString().split('T')[0];
                const today = new Date().toISOString().split('T')[0];
                
                let confirmMessage;
                if (selectedDate >= today) {
                    confirmMessage = "Remove this task?\n\nIt will be moved to Recently Deleted and can be restored from the menu.";
                } else {
                    const dateObj = new Date(selectedDate);
                    const dateStr = dateObj.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
                    confirmMessage = `Remove this task from ${dateStr} onward?\n\nIt will disappear from this date forward but remain visible on earlier dates.`;
                }
                
                if (confirm(confirmMessage)) {
                    deactivateTask(taskId);
                }
            }, LONG_PRESS_TIME);
        };

        const cancelPress = () => {
            clearTimeout(pressTimer);
        };

        item.addEventListener("touchstart", startPress);
        item.addEventListener("touchend", cancelPress);
        item.addEventListener("touchmove", cancelPress);
        item.addEventListener("mousedown", startPress);
        item.addEventListener("mouseup", cancelPress);
        item.addEventListener("mouseleave", cancelPress);
    });

    // Check if tutorial should be shown
    const tutorialCompleted = localStorage.getItem('tutorialCompleted');
    const isNewUser = document.body.dataset.newUser === 'true';
    
    if (!tutorialCompleted && isNewUser) {
        setTimeout(() => {
            showTutorial();
        }, 1000); // Show after 1 second
    }
});