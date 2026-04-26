const errorHandling = require('../support/pages/errorHandling');

describe('Error Handling', () => {
  it('Access a non-existent page', () => {
    errorHandling.visitNonExistentPage();
    errorHandling.getErrorMessage().should('exist');
  });
});