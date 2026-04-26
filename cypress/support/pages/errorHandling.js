class ErrorHandling { 
  visitNonExistentPage() { 
    cy.visit('/nonexistent'); 
  } 
  getErrorMessage() { 
    return cy.contains(/404|not found/i); 
  } 
} 
module.exports = new ErrorHandling();