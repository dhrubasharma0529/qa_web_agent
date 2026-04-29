const homePage = require('../support/pages/homePage');

describe('Projects Gallery', () => {
  it('User views projects gallery', () => {
    homePage.visit();
    homePage.scrollToCaseStudiesSection();
    cy.get('h2').contains('Case Studies').should('be.visible');
  });
});