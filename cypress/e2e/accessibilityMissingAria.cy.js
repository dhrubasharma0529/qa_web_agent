const accessibility = require('../support/pages/accessibility');

describe('Accessibility', () => {
  it('Check for missing ARIA labels on interactive elements', () => {
    const homePage = require('../support/pages/homePage');
    homePage.visit();
    accessibility.checkForMissingAriaLabels();
    cy.get('button#mobile-menu-toggle.mobile-menu-toggle').should('not.have.attr', 'aria-label');
  });
});