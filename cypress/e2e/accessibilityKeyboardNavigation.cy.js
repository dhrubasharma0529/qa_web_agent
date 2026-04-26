const accessibility = require('../support/pages/accessibility');

describe('Accessibility', () => {
  it('Test keyboard navigation for interactive elements', () => {
    const homePage = require('../support/pages/homePage');
    homePage.visit();
    accessibility.checkKeyboardNavigation();
    cy.get('input[name="name"]').focus().should('be.focused');
  });
});