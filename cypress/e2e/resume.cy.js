const homePage = require('../support/pages/homePage');

describe('Hero Section', () => {
  it('User navigates to the homepage and views the hero section', () => {
    homePage.visit();
    homePage.getHeroSection().should('be.visible');
    homePage.getPrimaryCTABtn().should('have.text', 'View My Work');
  });
});