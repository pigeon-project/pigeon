import { useState, useEffect } from 'react';
import './App.css';

interface Task {
  id: string;
  text: string;
  dueDate: string;
  priority: 'low' | 'medium' | 'high';
  completed: boolean;
}

function App() {
  const [tasks, setTasks] = useState<Task[]>(() => {
    const stored = localStorage.getItem('tasks');
    return stored ? JSON.parse(stored) : [];
  });
  const [description, setDescription] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [priority, setPriority] = useState<'low' | 'medium' | 'high'>('low');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');

  useEffect(() => {
    localStorage.setItem('tasks', JSON.stringify(tasks));
  }, [tasks]);

  useEffect(() => {
    document.body.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('theme', theme);
  }, [theme]);

  const resetForm = () => {
    setDescription('');
    setDueDate('');
    setPriority('low');
    setEditingId(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!description.trim()) return;

    if (editingId) {
      setTasks(tasks.map(t => t.id === editingId ? { ...t, text: description, dueDate, priority } : t));
    } else {
      setTasks([...tasks, { id: crypto.randomUUID(), text: description, dueDate, priority, completed: false }]);
    }
    resetForm();
  };

  const toggleComplete = (id: string) => {
    setTasks(tasks.map(t => t.id === id ? { ...t, completed: !t.completed } : t));
  };

  const removeTask = (id: string) => {
    setTasks(tasks.filter(t => t.id !== id));
  };

  const editTask = (task: Task) => {
    setDescription(task.text);
    setDueDate(task.dueDate);
    setPriority(task.priority);
    setEditingId(task.id);
  };

  return (
    <>
      <header>
        <h1>PigeonToDoApp</h1>
        <button onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
          {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
        </button>
      </header>
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Task description"
          value={description}
          onChange={e => setDescription(e.target.value)}
        />
        <input
          type="date"
          value={dueDate}
          onChange={e => setDueDate(e.target.value)}
        />
        <select value={priority} onChange={e => setPriority(e.target.value as any)}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <button type="submit">{editingId ? 'Update' : 'Add'} Task</button>
      </form>
      <ul className="task-list">
        {tasks.map(task => (
          <li key={task.id} className={`task-item ${task.priority} ${task.completed ? 'completed' : ''}`}>
            <div>
              <strong>{task.text}</strong><br />
              {task.dueDate && <small>Due: {task.dueDate}</small>}
            </div>
            <div className="task-actions">
              <button onClick={() => toggleComplete(task.id)}>{task.completed ? 'Undo' : 'Done'}</button>
              <button onClick={() => editTask(task)}>Edit</button>
              <button onClick={() => removeTask(task.id)}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

export default App;
