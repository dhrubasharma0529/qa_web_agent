const homePage = require('../support/pages/homePage');

describe('Experience Section', () => {
  it('User views experience section', () => {
    homePage.visit();
    homePage.scrollToExperienceSection();
    cy.get('h2').contains('Experience').should('be.visible');
  });
});