const homePage = require('../support/pages/homePage');

describe('Navigation', () => {
  it('Click on non-existent navigation link', () => {
    homePage.visit();
    homePage.getSkillsLink().first().click();
    cy.contains(/404|not found/i).should('exist');
  });
});