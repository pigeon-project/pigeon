import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';

test('allows users to add tasks', () => {
  render(<App />);
  const input = screen.getByPlaceholderText(/task description/i);
  fireEvent.change(input, { target: { value: 'Buy milk' } });
  const addButton = screen.getByRole('button', { name: /add task/i });
  fireEvent.click(addButton);
  expect(screen.getByText('Buy milk')).toBeInTheDocument();
});
