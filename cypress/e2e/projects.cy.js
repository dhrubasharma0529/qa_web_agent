const homePage = require('../support/pages/homePage');

describe('Projects/Portfolio Page', () => {
  it('User navigates to the Projects page', () => {
    homePage.visit();
    homePage.getProjectsLink().first().click();
    cy.get('h3').should('have.length.gte', 1);
  });
});