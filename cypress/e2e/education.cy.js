const homePage = require('../support/pages/homePage');

describe('Education Section', () => {
  it('User views education section', () => {
    homePage.visit();
    homePage.scrollToEducationSection();
    cy.get('h2').contains('Education').should('be.visible');
  });
});