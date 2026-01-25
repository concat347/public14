from models import ToDoModel

class ToDoService:
    def __init__(self):
        self.model = ToDoModel()

    def create(self, params):
        """Create a new ToDo item."""
        return self.model.create(params)

    def update(self, item_id, params):
        """Update an existing ToDo item."""
        return self.model.update(item_id, params)

    def delete(self, item_id):
        """Mark a ToDo item as deleted (soft delete)."""
        return self.model.delete(item_id)

    def list(self):
        """List all ToDo items."""
        return self.model.list_items()

    def get_by_id(self, item_id):
        """Get a ToDo item by its ID."""
        return self.model.get_by_id(item_id)
