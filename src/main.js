const taskForm = document.getElementById('task-form');
const taskInput = document.getElementById('task-input');
const taskDate = document.getElementById('task-date');
const taskPriority = document.getElementById('task-priority');
const taskList = document.getElementById('task-list');
const themeToggle = document.getElementById('theme-toggle');

let tasks = JSON.parse(localStorage.getItem('tasks') || '[]');
const savedTheme = localStorage.getItem('theme');
if (savedTheme === 'dark') {
  document.body.classList.add('dark');
}

function saveTasks() {
  localStorage.setItem('tasks', JSON.stringify(tasks));
}

function renderTasks() {
  taskList.innerHTML = '';
  tasks.forEach((task, index) => {
    const li = document.createElement('li');
    li.className = 'task';
    if (task.completed) li.classList.add('completed');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = task.completed;
    checkbox.addEventListener('change', () => {
      task.completed = checkbox.checked;
      saveTasks();
      renderTasks();
    });

    const span = document.createElement('span');
    span.textContent = task.text;
    if (task.due) {
      span.textContent += ` (due ${task.due})`;
    }
    span.classList.add(`priority-${task.priority}`);

    li.appendChild(checkbox);
    li.appendChild(span);
    taskList.appendChild(li);
  });
}

renderTasks();

taskForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = taskInput.value.trim();
  if (!text) return;
  tasks.push({
    text,
    due: taskDate.value,
    priority: taskPriority.value,
    completed: false,
  });
  saveTasks();
  renderTasks();
  taskForm.reset();
});

themeToggle.addEventListener('click', () => {
  document.body.classList.toggle('dark');
  localStorage.setItem('theme', document.body.classList.contains('dark') ? 'dark' : 'light');
});
